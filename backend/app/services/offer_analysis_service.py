"""On-demand, assumption-explicit Offer comparison and negotiation drafts."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable

from sqlalchemy.orm import Session

from app.db.types import utc_now
from app.models.career_profile import CareerProfile, CareerProfileDirection
from app.models.job_opportunity import JobOpportunity
from app.models.offer import Offer
from app.schemas.artifact import ArtifactProvenanceInput, ArtifactWriteInput
from app.schemas.career_insights import (
    AssumptionSource,
    NegotiationDraftRequest,
    NegotiationDraftResponse,
    OfferAnalysisItem,
    OfferAnalysisRequest,
    OfferAnalysisResponse,
)
from app.services import artifact_service


class OfferAnalysisError(ValueError):
    pass


class OfferAnalysisNotFoundError(OfferAnalysisError):
    pass


class OfferAnalysisConflictError(OfferAnalysisError):
    pass


def compare_offers(
    db: Session,
    *,
    user_pk: int,
    command: OfferAnalysisRequest,
) -> OfferAnalysisResponse:
    base_currency = command.base_currency.upper()
    offers = _owned_offers(db, user_pk, command.offer_ids)
    rates = {
        item.currency.upper(): item.rate_to_base for item in command.exchange_rates
    }
    if base_currency in rates and rates[base_currency] != Decimal("1"):
        raise OfferAnalysisError(
            f"base currency {base_currency} must use an identity exchange rate of 1"
        )
    rates.setdefault(base_currency, Decimal("1"))
    taxes = {item.offer_id: item for item in command.tax_assumptions}
    equity = {item.offer_id: item for item in command.equity_assumptions}
    bonus = {item.offer_id: item for item in command.bonus_assumptions}
    sources = _unique_sources(
        [item.source for item in command.exchange_rates]
        + [item.source for item in command.tax_assumptions]
        + [item.source for item in command.equity_assumptions]
        + [item.source for item in command.bonus_assumptions]
    )
    offer_fact_sources = _offer_fact_source_lines(offers)
    career_profile_constraints = _confirmed_profile_constraints(db, user_pk)

    items: list[OfferAnalysisItem] = []
    for offer in offers:
        opportunity = db.get(JobOpportunity, offer.job_opportunity_id)
        if opportunity is None or opportunity.user_id != user_pk:
            raise OfferAnalysisNotFoundError(offer.job_opportunity_id)
        terms = dict(offer.terms_json or {})
        missing: list[str] = []
        risks: list[str] = []
        assumptions: list[str] = []
        currency = str(terms.get("currency") or "").upper() or None
        annual_base = _annual_base(terms, missing, assumptions)
        rate = rates.get(currency) if currency else None
        if annual_base is not None and rate is None:
            missing.append(f"缺少 {currency} → {base_currency} 的汇率与来源")
        annual_base_converted = (
            annual_base * rate if annual_base is not None and rate else None
        )

        bonus_value = bonus.get(offer.id)
        if bonus_value is not None and not terms.get("bonus_text"):
            raise OfferAnalysisError(
                f"Offer {offer.id} has no confirmed bonus term to quantify"
            )
        annual_bonus_converted = _convert_assumption(
            bonus_value.annual_value if bonus_value else None,
            bonus_value.currency.upper() if bonus_value else None,
            rates,
            base_currency,
            missing,
            label="奖金",
        )
        if terms.get("bonus_text") and bonus_value is None:
            missing.append("奖金条款未转换为可比较的年化金额")
        equity_value = equity.get(offer.id)
        if equity_value is not None and not terms.get("equity_text"):
            raise OfferAnalysisError(
                f"Offer {offer.id} has no confirmed equity term to value"
            )
        annual_equity_converted = _convert_assumption(
            equity_value.annual_value if equity_value else None,
            equity_value.currency.upper() if equity_value else None,
            rates,
            base_currency,
            missing,
            label="股权",
        )
        if terms.get("equity_text") and equity_value is None:
            missing.append("股权条款缺少年化估值、方法与行情观察时点")

        after_tax = None
        tax = taxes.get(offer.id)
        cash = None
        if annual_base_converted is not None:
            cash = annual_base_converted + (annual_bonus_converted or Decimal("0"))
        tax_basis = terms.get("tax_basis")
        if tax_basis == "net" and cash is not None and bonus_value is None:
            after_tax = cash
            assumptions.append("原始基本薪资口径标记为税后，未再次扣税")
            if tax is not None:
                assumptions.append("未使用额外有效税率：原始基本薪资已明确为税后")
        elif tax_basis == "net" and bonus_value is not None:
            missing.append("基本薪资为税后口径，但奖金税务口径未明确，无法合并税后现金")
        elif tax_basis == "gross" and tax is not None and cash is not None:
            after_tax = cash * (Decimal("1") - tax.effective_rate)
            assumptions.append(
                f"税后现金按 {tax.jurisdiction} 有效税率 "
                f"{_decimal_text(tax.effective_rate * 100)}% 估算"
            )
        elif tax_basis == "gross" and tax is None:
            missing.append("缺少适用税制与有效税率，无法估算税后现金")
        elif tax_basis in {None, "unspecified"}:
            missing.append("薪资税前/税后口径未明确，无法估算税后现金")

        formalities = _current_term_formalities(offer)
        if not formalities or any(value != "written" for value in formalities):
            risks.append("当前 Offer 含非书面或来源形式不明的条款，口头承诺需书面确认")
        if not terms.get("response_deadline"):
            risks.append("未记录明确回复截止")
        if not terms.get("start_date"):
            missing.append("未记录入职日期")
        if terms.get("tax_basis") in {None, "unspecified"}:
            risks.append("薪资税前/税后口径未明确")
        total = None
        has_unquantified_component = bool(
            (terms.get("bonus_text") and bonus_value is None)
            or (terms.get("equity_text") and equity_value is None)
        )
        if after_tax is not None and not has_unquantified_component:
            total = after_tax + (annual_equity_converted or Decimal("0"))
        if equity_value is not None:
            assumptions.append(f"股权年化估值方法：{equity_value.method}")
        if bonus_value is not None:
            assumptions.append(f"奖金年化依据：{bonus_value.basis}")
        if currency and rate:
            assumptions.append(f"{currency} 按 {rate} {base_currency}/{currency} 换算")

        items.append(
            OfferAnalysisItem(
                offer_id=offer.id,
                job_opportunity_id=offer.job_opportunity_id,
                company_name=opportunity.company_name,
                job_title=opportunity.job_title,
                original_currency=currency,
                annual_base_original=_decimal_text(annual_base),
                annual_base_in_base_currency=_decimal_text(annual_base_converted),
                annual_bonus_in_base_currency=_decimal_text(annual_bonus_converted),
                annual_equity_in_base_currency=_decimal_text(annual_equity_converted),
                estimated_after_tax_cash=_decimal_text(after_tax),
                estimated_total_value=_decimal_text(total),
                missing_information=sorted(dict.fromkeys(missing)),
                risks=sorted(dict.fromkeys(risks)),
                assumptions=sorted(dict.fromkeys(assumptions)),
            )
        )
    generated_at = utc_now()
    report = _report_markdown(
        items,
        base_currency=base_currency,
        career_profile_constraints=career_profile_constraints,
        user_constraints=command.user_constraints,
        offer_fact_sources=offer_fact_sources,
        sources=sources,
    )
    artifact_id = None
    if command.save_artifact:
        try:
            artifact = artifact_service.save_artifact_explicitly(
                db,
                user_pk=user_pk,
                operation_key=command.operation_key or "",
                artifact_kind="offer_comparison",
                version=ArtifactWriteInput(
                    title="Offer 比较报告",
                    content_text=report,
                    content_format="markdown",
                ),
            )
        except artifact_service.ArtifactConflictError as exc:
            raise OfferAnalysisConflictError(str(exc)) from exc
        except artifact_service.ArtifactDomainError as exc:
            raise OfferAnalysisError(str(exc)) from exc
        artifact_id = artifact.id
    return OfferAnalysisResponse(
        generated_at=generated_at,
        base_currency=base_currency,
        items=items,
        career_profile_constraints=career_profile_constraints,
        user_constraints=command.user_constraints,
        source_observations=sources,
        report_markdown=report,
        artifact_id=artifact_id,
    )


def build_negotiation_draft(
    db: Session,
    *,
    user_pk: int,
    offer_id: str,
    command: NegotiationDraftRequest,
) -> NegotiationDraftResponse:
    offer = (
        db.query(Offer)
        .filter(Offer.id == offer_id, Offer.user_id == user_pk)
        .one_or_none()
    )
    if offer is None:
        raise OfferAnalysisNotFoundError(offer_id)
    opportunity = db.get(JobOpportunity, offer.job_opportunity_id)
    if opportunity is None or opportunity.user_id != user_pk:
        raise OfferAnalysisNotFoundError(offer.job_opportunity_id)
    salutation = "您好，"
    thanks = {
        "professional": "感谢您提供这份 Offer。我认真审阅了目前的条款。",
        "warm": "非常感谢团队的认可和这份 Offer，我很期待继续推进。",
        "concise": "感谢这份 Offer。我已审阅当前条款。",
    }[command.tone]
    constraints = "\n".join(f"- {item}" for item in command.constraints)
    draft = (
        f"{salutation}\n\n{thanks}\n\n"
        f"我希望进一步沟通以下事项：{command.objective.strip()}\n"
        + (f"\n我目前需要同时考虑的约束：\n{constraints}\n" if constraints else "")
        + "\n请问团队是否方便讨论可调整空间，或提供可选方案？\n\n"
        "本次沟通不构成对 Offer 的接受、拒绝或签署。\n\n谢谢。"
    )
    artifact_id = None
    if command.save_artifact:
        try:
            artifact = artifact_service.save_artifact_explicitly(
                db,
                user_pk=user_pk,
                operation_key=command.operation_key or "",
                artifact_kind="negotiation_draft",
                version=ArtifactWriteInput(
                    title=f"{opportunity.company_name} Offer 谈判草稿",
                    content_text=draft,
                    content_format="markdown",
                    provenance=ArtifactProvenanceInput(
                        source_owner_type="job_opportunity",
                        source_owner_id=opportunity.id,
                    ),
                ),
                source_owner_checker=_job_owner_checker,
            )
        except artifact_service.ArtifactConflictError as exc:
            raise OfferAnalysisConflictError(str(exc)) from exc
        except artifact_service.ArtifactDomainError as exc:
            raise OfferAnalysisError(str(exc)) from exc
        artifact_id = artifact.id
    return NegotiationDraftResponse(
        offer_id=offer.id,
        draft_markdown=draft,
        send_status="not_sent",
        execution_note=(
            "仅生成草稿；尚未调用具有真实 handler、有效连接、参数级权限和 "
            "receipt/read-back 的外部发送 Tool。"
        ),
        artifact_id=artifact_id,
    )


def _owned_offers(db: Session, user_pk: int, ids: list[str]) -> list[Offer]:
    rows = db.query(Offer).filter(Offer.user_id == user_pk, Offer.id.in_(ids)).all()
    by_id = {row.id: row for row in rows}
    missing = [offer_id for offer_id in ids if offer_id not in by_id]
    if missing:
        raise OfferAnalysisNotFoundError(missing[0])
    return [by_id[offer_id] for offer_id in ids]


def _annual_base(
    terms: dict[str, object], missing: list[str], assumptions: list[str]
) -> Decimal | None:
    raw = terms.get("base_salary_amount")
    period = terms.get("pay_period")
    if raw in (None, ""):
        missing.append("缺少基本薪资金额")
        return None
    try:
        amount = Decimal(str(raw))
    except InvalidOperation:
        missing.append("基本薪资金额不可解析")
        return None
    if period == "annual":
        return amount
    if period == "monthly":
        assumptions.append("月薪按 12 个月年化")
        return amount * 12
    if period == "hourly":
        assumptions.append("时薪按每周 40 小时、每年 52 周年化")
        return amount * 40 * 52
    if period == "total":
        assumptions.append("总额按一年覆盖期处理；实际覆盖期需核验")
        return amount
    missing.append("缺少薪资计薪周期")
    return None


def _convert_assumption(
    value: Decimal | None,
    currency: str | None,
    rates: dict[str, Decimal],
    base_currency: str,
    missing: list[str],
    *,
    label: str,
) -> Decimal | None:
    if value is None or currency is None:
        return None
    rate = rates.get(currency)
    if rate is None:
        missing.append(f"{label}缺少 {currency} → {base_currency} 汇率")
        return None
    return value * rate


def _current_term_formalities(offer: Offer) -> set[str]:
    """Return formality only for sources that own current terms.

    PostgreSQL JSONB does not preserve object insertion order, so “the last
    excerpt in the dict” cannot identify the current source.  Match the source
    snapshots attached to current terms instead; fall back to the Offer's
    explicit last-source identity for older rows without per-term provenance.
    """

    current_sources = [
        value
        for value in (offer.term_sources_json or {}).values()
        if isinstance(value, dict)
    ]
    excerpts = [
        value
        for value in (offer.source_excerpts_json or {}).values()
        if isinstance(value, dict)
    ]
    result: set[str] = set()
    for source in current_sources:
        matched = False
        for excerpt in excerpts:
            if excerpt.get("source") == source and excerpt.get("formality"):
                result.add(str(excerpt["formality"]))
                matched = True
                break
        if not matched:
            result.add("unknown")
    if result:
        return result
    for excerpt in excerpts:
        source = excerpt.get("source")
        if (
            isinstance(source, dict)
            and source.get("identity") == offer.last_source_identity
            and source.get("kind") == offer.last_source_kind
            and excerpt.get("formality")
        ):
            return {str(excerpt["formality"])}
    # Legacy/test rows may have an excerpt but no embedded source snapshot.
    return {
        str(excerpt["formality"]) for excerpt in excerpts if excerpt.get("formality")
    }


def _offer_fact_source_lines(offers: list[Offer]) -> list[str]:
    result: list[str] = []
    for offer in offers:
        snapshots = {
            (
                str(source.get("kind") or "unknown"),
                str(source.get("identity") or "unknown"),
                str(source.get("version"))
                if source.get("version") is not None
                else None,
                str(source.get("observed_at") or "unknown"),
            )
            for source in (offer.term_sources_json or {}).values()
            if isinstance(source, dict)
        }
        if not snapshots:
            snapshots = {
                (
                    offer.last_source_kind,
                    offer.last_source_identity,
                    offer.last_source_version,
                    offer.last_source_observed_at.isoformat(),
                )
            }
        for kind, identity, version, observed_at in sorted(
            snapshots,
            key=lambda value: tuple(item or "" for item in value),
        ):
            version_text = f"，版本 {version}" if version else ""
            result.append(
                f"Offer {offer.id}：{kind}:{identity}{version_text}"
                f"（观察时间 {observed_at}）"
            )
    return result


def _unique_sources(values: Iterable[AssumptionSource]) -> list[AssumptionSource]:
    seen: set[tuple[str, str]] = set()
    result: list[AssumptionSource] = []
    for value in values:
        key = (value.identity, value.observed_at.isoformat())
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _confirmed_profile_constraints(db: Session, user_pk: int) -> list[str]:
    """Render only canonical, currently relevant CareerProfile directions.

    Paused and archived directions remain historical product facts but are not
    silently treated as current Offer decision constraints.
    """

    rows = (
        db.query(CareerProfileDirection)
        .join(
            CareerProfile,
            CareerProfile.id == CareerProfileDirection.career_profile_id,
        )
        .filter(
            CareerProfile.user_id == user_pk,
            CareerProfileDirection.lifecycle.in_(["active", "exploring"]),
        )
        .order_by(
            CareerProfileDirection.priority.asc(),
            CareerProfileDirection.confirmed_at.asc(),
            CareerProfileDirection.id.asc(),
        )
        .all()
    )
    labels = {
        "role_keywords": "岗位关键词",
        "seniority": "职级",
        "locations": "地点",
        "work_modes": "办公方式",
        "industries": "行业",
        "technologies": "技术",
        "exclusions": "排除项",
    }
    rendered: list[str] = []
    for row in rows:
        criteria = dict(row.criteria_json or {})
        parts: list[str] = []
        for key, label in labels.items():
            raw = criteria.get(key)
            if isinstance(raw, list) and raw:
                parts.append(f"{label}={','.join(str(value) for value in raw)}")
        salary_min = criteria.get("salary_min")
        salary_max = criteria.get("salary_max")
        if salary_min is not None or salary_max is not None:
            currency = str(criteria.get("salary_currency") or "未注明币种")
            if salary_min is not None and salary_max is not None:
                salary = f"{salary_min}–{salary_max} {currency}"
            elif salary_min is not None:
                salary = f">={salary_min} {currency}"
            else:
                salary = f"<={salary_max} {currency}"
            parts.append(f"薪资范围={salary}")
        detail = "；".join(parts) if parts else "未设置细分条件"
        rendered.append(f"{row.label}（{row.lifecycle}）：{detail}")
    return rendered


def _report_markdown(
    items: list[OfferAnalysisItem],
    *,
    base_currency: str,
    career_profile_constraints: list[str],
    user_constraints: list[str],
    offer_fact_sources: list[str],
    sources: list[AssumptionSource],
) -> str:
    lines = [
        "# Offer 比较报告",
        "",
        f"统一展示币种：{base_currency}",
        "",
        "> 所有换算、税后、股权估值和总价值均为带假设的分析，绝不回写 Offer 条款事实。",
        "",
    ]
    if career_profile_constraints:
        lines.extend(["## 已确认求职档案约束", ""])
        lines.extend(f"- {item}" for item in career_profile_constraints)
        lines.append("")
    if user_constraints:
        lines.extend(["## 当前明确约束", ""])
        lines.extend(f"- {item}" for item in user_constraints)
        lines.append("")
    lines.extend(["## Offer 条款事实来源与观察时点", ""])
    lines.extend(f"- {item}" for item in offer_fact_sources)
    if not offer_fact_sources:
        lines.append("- 未找到可回溯的 Offer 条款事实来源。")
    lines.append("")
    for item in items:
        lines.extend(
            [
                f"## {item.company_name} · {item.job_title}",
                "",
                f"- 年化基本薪资（{base_currency}）：{item.annual_base_in_base_currency or '无法计算'}",
                f"- 年化奖金（{base_currency}）：{item.annual_bonus_in_base_currency or '未计入'}",
                f"- 年化股权（{base_currency}）：{item.annual_equity_in_base_currency or '未计入'}",
                f"- 估算税后现金（{base_currency}）：{item.estimated_after_tax_cash or '无法计算'}",
                f"- 估算总价值（{base_currency}）：{item.estimated_total_value or '无法计算'}",
                "",
                "### 假设",
            ]
        )
        lines.extend(f"- {value}" for value in item.assumptions or ["无额外量化假设"])
        lines.extend(["", "### 缺失与风险"])
        lines.extend(
            f"- {value}"
            for value in item.missing_information + item.risks
            or ["当前输入未识别到额外缺失或风险"]
        )
        lines.append("")
    lines.extend(["## 外部假设来源与观察时点", ""])
    lines.extend(
        f"- {source.identity}（观察时间 {source.observed_at.isoformat()}）"
        + (f" — {source.url}" if source.url else "")
        for source in sources
    )
    if not sources:
        lines.append("- 本次未使用外部汇率、税务、行情或估值数据；相应结果保持缺失。")
    return "\n".join(lines)


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01")), "f")


def _job_owner_checker(
    db: Session, user_pk: int, owner_type: str, owner_id: str
) -> bool:
    return bool(
        owner_type == "job_opportunity"
        and db.query(JobOpportunity.id)
        .filter(JobOpportunity.id == owner_id, JobOpportunity.user_id == user_pk)
        .scalar()
    )


__all__ = [
    "OfferAnalysisConflictError",
    "OfferAnalysisError",
    "OfferAnalysisNotFoundError",
    "build_negotiation_draft",
    "compare_offers",
]
