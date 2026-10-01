"""Build traceable question candidates from frozen original text.

Answers are verbatim source spans. This generator does not certify semantic
quality; the review state is explicit in every record.
"""

from __future__ import annotations

import itertools
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .acquire import LOCK, OUT, SEED

HERE = Path(__file__).parent
RESULT = HERE / "questions.candidate.jsonl"

TITLES = {
    "py-asyncio": "Python asyncio Tasks",
    "react-effects": "React Synchronizing with Effects",
    "postgres-isolation": "PostgreSQL Transaction Isolation",
    "langchain-agents": "LangChain Agents",
    "mcp-tools": "MCP Tools specification",
    "who-patient-safety": "WHO Patient safety",
    "w3c-non-text-content": "WCAG 2.2 Non-text Content",
    "investor-gov-introduction": "SEC Introduction to Investing",
    "vue-reactivity-zh": "Vue 响应式基础",
    "kubernetes-deployment-zh": "Kubernetes Deployment",
    "aliyun-agent-zh": "阿里云百炼智能体应用",
    "labor-contract-law-zh": "中华人民共和国劳动合同法",
    "civil-code-zh": "中华人民共和国民法典",
    "antimicrobial-use-zh": "抗菌药物临床应用管理办法",
    "infection-management-zh": "医院感染管理办法",
    "hand-hygiene-zh": "医务人员手卫生规范",
    "docker-volumes": "Docker Volumes",
    "mdn-promises": "MDN Using promises",
    "nist-csf": "NIST Cybersecurity Framework",
    "kubernetes-probes-en": "Kubernetes Liveness, Readiness, and Startup Probes",
    "git-rebase": "Git rebase",
    "ftc-start-security": "FTC Start with Security",
    "medlineplus-medication-errors": "MedlinePlus Medication Errors",
    "rfc-http-semantics": "RFC 9110 HTTP Semantics",
    "react-state-zh": "React State：组件的记忆",
    "vue-computed-zh": "Vue 计算属性",
    "kubernetes-probes-zh": "Kubernetes 存活、就绪和启动探针",
    "food-safety-law-zh": "中华人民共和国食品安全法",
    "accounting-basic-zh": "企业会计准则——基本准则",
    "teachers-law-zh": "中华人民共和国教师法",
    "miit-standards-zh": "2025年工业和信息化标准工作要点",
    "aliyun-rag-zh": "阿里云百炼知识库 API 指南",
    "privacy-law-zh": "中华人民共和国个人信息保护法",
    "safety-production-law-zh": "中华人民共和国安全生产法",
    "patent-law-zh": "中华人民共和国专利法",
    "sklearn-cross-validation": "scikit-learn Cross-validation",
    "pandas-groupby": "pandas Group by",
    "python-logging": "Python Logging HOWTO",
    "education-discipline-zh": "中小学教育惩戒规则（试行）",
    "ecommerce-law-samr-zh": "中华人民共和国电子商务法",
    "owasp-access-control": "OWASP Broken Access Control",
    "who-food-safety": "WHO Food safety",
}
MANUAL = HERE / "manual_facts.json"
TOPIC_TERMS = {
    "py-asyncio": r"task|coroutine|timeout|event loop|await|future|cancel|asynchron",
    "react-effects": r"effect|component|render|dependenc|cleanup|synchroniz",
    "postgres-isolation": r"transaction|isolation|serializ|read committed|repeatable|snapshot|predicate",
    "langchain-agents": r"agent|tool|model|middleware|hook|state|context",
    "mcp-tools": r"tool|server|client|invocation|capabilit",
    "who-patient-safety": r"patient|harm|health|safety|sepsis|infection|medication",
    "w3c-non-text-content": r"non-text|text alternative|image|accessib|screen reader|content",
    "investor-gov-introduction": r"invest|asset|risk|goal|portfolio|financial",
    "docker-volumes": r"volume|container|mount|storage|data|bind",
    "mdn-promises": r"promise|then|catch|async|error|chain",
    "nist-csf": r"cybersecurity|risk|framework|organization",
    "kubernetes-probes-en": r"probe|kubelet|container|readiness|liveness|startup|pod",
    "git-rebase": r"rebase|commit|branch|patch|merge|upstream",
    "ftc-start-security": r"data|security|information|privacy|account|password|authenticat",
    "medlineplus-medication-errors": r"medication|medicine|error|prescription|pharmac|dose|side effect",
    "rfc-http-semantics": r"http|request|response|header|field|status|method|cache|content",
    "sklearn-cross-validation": r"cross.valid|train|test|split|model|estimator|score|fold",
    "pandas-groupby": r"group|aggregate|transform|filter|dataframe|series",
    "python-logging": r"log|handler|record|level|filter|formatter",
    "owasp-access-control": r"access|control|authoriz|policy|permission|user",
    "who-food-safety": r"food|hazard|disease|safety|bacteria|virus|contamin|consumer",
    "vue-reactivity-zh": r"响应式|ref|reactive|Vue|属性|依赖",
    "kubernetes-deployment-zh": r"Deployment|ReplicaSet|Pod|副本|更新|回滚",
    "aliyun-agent-zh": r"智能体|Agent|工作流|高代码|知识库",
    "labor-contract-law-zh": r"劳动|用人单位|劳动者|合同|试用期|工资",
    "civil-code-zh": r"民事|侵权|合同|继承|物权|人格权|婚姻",
    "antimicrobial-use-zh": r"抗菌药物|医疗机构|医师|药师|处方",
    "infection-management-zh": r"医院感染|医疗机构|医务人员|卫生",
    "hand-hygiene-zh": r"手卫生|洗手|消毒|医疗机构",
    "react-state-zh": r"state|React|组件|渲染|变量|Hook",
    "vue-computed-zh": r"计算属性|getter|依赖|缓存",
    "kubernetes-probes-zh": r"探针|Pod|容器|kubelet|状态码",
    "food-safety-law-zh": r"食品|生产经营|监管|标准|检验",
    "accounting-basic-zh": r"会计|财务|企业|资产|收入|费用",
    "teachers-law-zh": r"教师|学校|教育|教学|资格",
    "miit-standards-zh": r"标准|产业|制造|人工智能",
    "aliyun-rag-zh": r"知识库|检索|API|切片|应用|文件",
    "privacy-law-zh": r"个人信息|处理者|数据|隐私|信息",
    "safety-production-law-zh": r"安全生产|生产经营|事故|应急|从业人员",
    "patent-law-zh": r"专利|发明|申请|权利|实施",
    "education-discipline-zh": r"教育|惩戒|学校|学生|教师|家长",
    "ecommerce-law-samr-zh": r"电子商务|平台|经营者|交易|消费者|支付",
}

ZH_OPERATORS = ("是指", "指的是", "应当", "必须", "不得", "可以", "包括", "分为")
EN_OPERATORS = (
    "refers to",
    "must",
    "should",
    "requires",
    "allows",
    "includes",
    "means",
    "include",
    "can",
    "are",
    "is",
)


def source_units(source: dict, content: str) -> list[dict]:
    language = source["language"]
    pattern = (
        r"[^。！？\n]{19,240}[。！？]" if language == "zh" else r"[^.!?\n]{34,320}[.!?]"
    )
    found = []
    for match in re.finditer(pattern, content):
        quote = match.group().strip()
        start = match.start() + len(match.group()) - len(match.group().lstrip())
        if quote.endswith(("?", "？")):
            continue
        if quote.lower().endswith(("; i.", "; e.", " i.", " e.")):
            continue
        if re.search(
            r"[{}<>]|https?://|\b(?:print|return|import)\s*\(|\bExample\s*#", quote
        ):
            continue
        if language == "zh":
            article = re.match(
                r"第[一二三四五六七八九十百千万零〇0-9]+条[\s\u3000]*", quote
            )
            if source["id"] == "civil-code-zh" and not article:
                continue
            body = quote[article.end() :] if article else quote
            operator = next(
                (
                    op
                    for op in sorted(
                        ZH_OPERATORS,
                        key=lambda op: (
                            body.find(op) if op in body else 10**9,
                            -len(op),
                        ),
                    )
                    if op in body
                ),
                None,
            )
            if not operator:
                continue
            subject, rest = body.split(operator, 1)
            subject = subject.strip(" \u3000：:，,；;、")
            if not (2 <= len(subject) <= 26 and len(rest) >= 7):
                continue
            if re.match(
                r"^(本|其|它|此|上述|以下|这|那|其中|对于|关于|如果|当|然而|由于|例如|另一个|并且|即使|到|根据|因此|通过|除了|务[，,]|资格|损害赔偿[，,]|的|则|权的|理个人信息|时[，,]|一般$|你|您|12\s*个月)",
                subject,
            ):
                continue
            if re.search(r"[。！？；;（）()]|  |\d{4}年", subject) or subject.endswith(
                ("的", "自", "从", "在", "时", "后", "但是")
            ):
                continue
            article_ref = article.group().strip() if article else ""
            prefix = f"根据《{TITLES[source['id']]}》{article_ref}，"
            if operator in ("是指", "指的是", "是"):
                question = f"{prefix}{subject}指什么？"
            elif operator == "包括":
                question = f"{prefix}{subject}包括哪些内容？"
            elif operator == "分为":
                question = f"{prefix}{subject}如何分类？"
            elif operator == "不得":
                question = f"{prefix}{subject}有哪些禁止性规定？"
            elif operator == "可以":
                question = f"{prefix}{subject}可以采取什么做法？"
            else:
                question = f"{prefix}{subject}有哪些要求？"
        else:
            body = re.sub(r"^[A-Z][A-Za-z0-9 :/(),-]{2,50}\s+[¶#]\s*", "", quote)
            match_op = re.search(
                r"\b(" + "|".join(re.escape(op) for op in EN_OPERATORS) + r")\b",
                body,
                flags=re.I,
            )
            if not match_op:
                continue
            operator = match_op.group().lower()
            subject = body[: match_op.start()].strip(" :;,-")
            rest = body[match_op.end() :]
            if not (4 <= len(subject) <= 48 and len(rest) >= 16):
                continue
            if re.match(
                r"(?i)^(this|that|it|they|we|you|there|these|those|if|for|note|example|as|in|the following|a user|what|how|when|why|where|because|by|to|now|both|some|with|while|using|after|before|no one|nor|or|unlike|however|again|only|let|verify|sent|write|list|sometimes|but|learn|no further|the idea|another option|numerous factors|others|my|work)\b",
                subject,
            ):
                continue
            if "\n" in subject or re.search(
                r"[{}<>;,=?]|\d{4}|\b(?:does not|do not|did not|that|which|who|while|when|where|because|as|since)\b",
                subject,
                re.I,
            ):
                continue
            if not re.match(r"[A-Z0-9]", subject):
                continue
            if len(subject.split()) > 6 or re.search(
                r"(?i)\b(previous|above|following|below|license|licensed|on this page)\b",
                quote,
            ):
                continue
            if re.search(
                r"(?i)\b(this|that|these|those|here|there)\b", subject
            ) or subject.endswith("usually"):
                continue
            if not quote[0].isupper() or re.search(
                r"\b(?:click|press|shown here|in the example)\b", quote, re.I
            ):
                continue
            prefix = f"According to {TITLES[source['id']]}, "
            if operator in ("is", "are", "means", "refers to"):
                question = f"{prefix}what does the document state about {subject}?"
            elif operator in ("include", "includes"):
                question = f"{prefix}what does {subject} include?"
            elif operator == "can":
                question = f"{prefix}what can {subject} do?"
            elif operator == "allows":
                question = f"{prefix}what does {subject} allow?"
            else:
                question = f"{prefix}what does the guidance require of {subject}?"
        if len(question) > 190 or len(quote) > 300:
            continue
        if len(set(quote)) < 15:
            continue
        if not re.search(TOPIC_TERMS[source["id"]], quote, re.I):
            continue
        if language == "zh" and subject in (
            "你",
            "您",
            "它",
            "组织",
            "该单位",
            "报的部门",
            "一款规定事项的",
            "更高级别的编排器",
        ):
            continue
        if language == "en" and re.match(
            r"(?i)^(all|the most|the goal|usually|here|of most|each year|immediate execution)\b",
            subject,
        ):
            continue
        if source["id"] == "ftc-start-security" and quote.startswith(
            "Security can’t be"
        ):
            continue
        if source["id"] == "rfc-http-semantics" and quote.startswith(
            "The field value is evaluated"
        ):
            continue
        rejected = {
            ("py-asyncio", "Tasks are only scheduled"),
            ("react-effects", "Setting state immediately in an Effect"),
            ("w3c-non-text-content", "CAPTCHAs are a controversial"),
            ("w3c-non-text-content", "Non-text information is available"),
            ("kubernetes-deployment-zh", "显示应用中有多少副本"),
            ("pandas-groupby", "GroupBy operations (though"),
            ("education-discipline-zh", "学校、教育行政部门应当"),
            ("who-food-safety", "Most diseases are not"),
        }
        if any(
            source["id"] == source_id and quote.startswith(prefix)
            for source_id, prefix in rejected
        ):
            continue
        rewrites = {
            (
                "react-effects",
                "Buying is not caused by rendering",
            ): "According to React, what causes a buying action?",
            (
                "postgres-isolation",
                "The other three levels are defined",
            ): "How does the SQL standard define the three isolation levels below Serializable?",
            (
                "langchain-agents",
                "An agent is a model",
            ): "How does LangChain define an agent?",
            (
                "langchain-agents",
                "Middleware is the primitive",
            ): "What role does middleware play in customizing a LangChain agent?",
            (
                "langchain-agents",
                "A harness is everything",
            ): "What components make up an agent harness in this LangChain guide?",
            (
                "kubernetes-probes-zh",
                "探针的成功与否仅由响应状态码决定",
            ): "Kubernetes HTTP 探针依据响应中的什么信息判断成功？",
            (
                "ecommerce-law-samr-zh",
                "电子商务平台经营者知道或者应当知道",
            ): "平台明知或应知商家侵害消费者权益却未采取必要措施时，依法承担什么责任？",
            (
                "docker-volumes",
                "The containers can't access",
            ): "In Docker's volume example, can one container access another container's logs?",
            (
                "rfc-http-semantics",
                "Any party can request",
            ): "Who can request registration of an HTTP field?",
            (
                "rfc-http-semantics",
                "Conflicts are most likely",
            ): "Which HTTP request method is most likely to encounter conflicts?",
        }
        for (source_id, prefix), replacement in rewrites.items():
            if source["id"] == source_id and quote.startswith(prefix):
                question = replacement
        found.append(
            {
                "source_id": source["id"],
                "question": question,
                "quote": quote,
                "start": start,
                "end": start + len(quote),
                "operator": operator,
                "position": start / len(content),
            }
        )
    return found


def manual_units(source: dict, content: str) -> list[dict]:
    facts = json.loads(MANUAL.read_text(encoding="utf-8"))
    found = []
    for fact in facts:
        if fact["source_id"] != source["id"]:
            continue
        start = content.find(fact["start"])
        if start < 0:
            raise ValueError(f"Manual start not in {source['id']}: {fact['start']}")
        end = content.find(fact["end"], start) + len(fact["end"])
        if end < start + len(fact["start"]):
            raise ValueError(f"Manual end not in {source['id']}: {fact['end']}")
        quote = content[start:end]
        if len(quote) > 380:
            raise ValueError(f"Manual quote too long in {source['id']}")
        found.append(
            {
                "source_id": source["id"],
                "question": fact["question"],
                "quote": quote,
                "start": start,
                "end": end,
                "operator": "manual",
                "position": start / len(content),
            }
        )
    return found


def spaced_select(items: list[dict], count: int) -> list[dict]:
    """Pick facts across the entire document while avoiding near duplicates."""
    selected = []
    seen = set()
    for target in [i / max(1, count - 1) for i in range(count)]:
        ranked = sorted(
            items,
            key=lambda x: (
                0 if x["operator"] == "manual" else 1,
                abs(x["position"] - target),
                abs(len(x["quote"]) - 125),
            ),
        )
        for item in ranked:
            key = re.sub(r"\W", "", item["question"]).lower()
            if key in seen or any(item["start"] == old["start"] for old in selected):
                continue
            selected.append(item)
            seen.add(key)
            break
    return selected


def evidence(item: dict, hashes: dict) -> dict:
    return {
        "source_id": item["source_id"],
        "start": item["start"],
        "end": item["end"],
        "quote": item["quote"],
        "text_sha256": hashes[item["source_id"]],
    }


def make_question(parts: list[dict], kind: str, language: str, hashes: dict) -> dict:
    if len(parts) == 1:
        query = parts[0]["question"]
        answer = clean_answer(parts[0]["quote"], language)
    else:
        if language == "zh":
            query = "请分别回答以下问题，并说明各自依据：\n" + "\n".join(
                f"{i}. {part['question']}" for i, part in enumerate(parts, 1)
            )
            answer = "\n".join(
                f"{i}. {clean_answer(part['quote'], language)}"
                for i, part in enumerate(parts, 1)
            )
        else:
            query = "Answer each question and cite its source:\n" + "\n".join(
                f"{i}. {part['question']}" for i, part in enumerate(parts, 1)
            )
            answer = "\n".join(
                f"{i}. {clean_answer(part['quote'], language)}"
                for i, part in enumerate(parts, 1)
            )
    source_ids = list(dict.fromkeys(part["source_id"] for part in parts))
    return {
        "language": language,
        "question": query,
        "reference_answer": answer,
        "task_type": kind,
        "intent_count": len(parts),
        "source_ids": source_ids,
        "evidence": [evidence(part, hashes) for part in parts],
        "answerability": "full",
        "review_status": "programmatic_candidate",
    }


def clean_answer(quote: str, language: str) -> str:
    quote = re.sub(
        r"-\s*\d+\s*-\s*国家卫生健康委员会发布\s*国家卫生健康委员会规章", "", quote
    )
    quote = re.sub(r"\n\s*\d+\s*\n", "", quote)
    if language == "zh":
        quote = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", quote)
    return re.sub(r"\s+", " ", quote).strip()


def assign_source_disjoint_splits(questions: list[dict], sources: list[dict]) -> None:
    """Keep every source and its connected cross-source questions in one split."""
    parent = {source["id"]: source["id"] for source in sources}

    def find(source_id: str) -> str:
        while parent[source_id] != source_id:
            source_id = parent[source_id]
        return source_id

    for question in questions:
        first = find(question["source_ids"][0])
        for source_id in question["source_ids"][1:]:
            parent[find(source_id)] = first
    groups = defaultdict(set)
    for source in sources:
        groups[find(source["id"])].add(source["id"])
    source_language = {source["id"]: source["language"] for source in sources}
    target_splits = ("dev", "calibration", "holdout_candidate")
    source_split = {}
    for language in ("zh", "en"):
        totals = {split: 0 for split in target_splits}
        components = [
            ids
            for ids in groups.values()
            if source_language[next(iter(ids))] == language
        ]
        components.sort(
            key=lambda ids: (
                -sum(bool(set(question["source_ids"]) & ids) for question in questions)
            )
        )
        for ids in components:
            split = min(target_splits, key=lambda name: totals[name])
            count = sum(
                bool(set(question["source_ids"]) & ids) for question in questions
            )
            totals[split] += count
            source_split.update({source_id: split for source_id in ids})
    for question in questions:
        splits = {source_split[source_id] for source_id in question["source_ids"]}
        assert len(splits) == 1
        question["split"] = splits.pop()


def main() -> None:
    sources = json.loads(SEED.read_text(encoding="utf-8"))
    frozen = [
        json.loads(line)
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert {row["id"] for row in sources} == set(TITLES)
    hashes = {row["id"]: row["text_sha256"] for row in frozen}
    candidates = {}
    for source in sources:
        content = (OUT / "text" / (source["id"] + ".txt")).read_text(encoding="utf-8")
        candidates[source["id"]] = manual_units(source, content) + source_units(
            source, content
        )
        for item in candidates[source["id"]]:
            assert content[item["start"] : item["end"]] == item["quote"]
    # Six single-fact questions per source where possible; allocate shortfall
    # to longer documents of the same language, never inventing missing facts.
    chosen = defaultdict(list)
    for language in ("zh", "en"):
        group = [row for row in sources if row["language"] == language]
        for row in group:
            chosen[row["id"]] = spaced_select(candidates[row["id"]], 6)
        target = 126
        while sum(len(chosen[row["id"]]) for row in group) < target:
            options = []
            for row in group:
                ident = row["id"]
                available = [
                    item
                    for item in candidates[ident]
                    if all(
                        item["start"] != old["start"]
                        and item["question"] != old["question"]
                        for old in chosen[ident]
                    )
                ]
                if available:
                    item = max(
                        available,
                        key=lambda x: (
                            x["operator"] == "manual",
                            min(
                                (
                                    abs(x["start"] - old["start"])
                                    for old in chosen[ident]
                                ),
                                default=999999,
                            ),
                        ),
                    )
                    options.append(
                        (len(chosen[ident]), -len(candidates[ident]), ident, item)
                    )
            if not options:
                raise ValueError(
                    f"Insufficient grounded single facts for {language}: "
                    f"{sum(len(chosen[row['id']]) for row in group)}"
                )
            _, _, ident, item = min(options)
            chosen[ident].append(item)
    questions = []
    for source in sources:
        for item in chosen[source["id"]]:
            questions.append(
                make_question([item], "single_fact", source["language"], hashes)
            )
    # Next stage: evidence-separated and cross-source questions are assembled
    # from already selected facts, with every answer sentence still verbatim.
    for language in ("zh", "en"):
        group = [row for row in sources if row["language"] == language]
        pools = {}
        for row in group:
            items = sorted(chosen[row["id"]], key=lambda x: x["start"])
            pairs = [
                pair
                for pair in itertools.combinations(items, 2)
                if pair[1]["position"] - pair[0]["position"] >= 0.15
                and pair[1]["start"] - pair[0]["end"] >= 800
            ]
            pools[row["id"]] = sorted(
                pairs,
                key=lambda pair: pair[1]["position"] - pair[0]["position"],
                reverse=True,
            )
        long = []
        for round_index in range(6):
            for row in group:
                pool = pools[row["id"]]
                if len(pool) > round_index:
                    long.append(pool[round_index])
                if len(long) == 42:
                    break
            if len(long) == 42:
                break
        if len(long) < 42:
            raise ValueError(
                f"Insufficient distinct long-span pairs for {language}: {len(long)}"
            )
        for pair in long:
            questions.append(
                make_question(list(pair), "long_span_single_source", language, hashes)
            )
    # Same-language, related-domain pairs only. Both original sources are needed.
    related_pairs = {
        "en": [
            ("py-asyncio", "python-logging"),
            ("react-effects", "mdn-promises"),
            ("postgres-isolation", "rfc-http-semantics"),
            ("langchain-agents", "mcp-tools"),
            ("who-patient-safety", "medlineplus-medication-errors"),
            ("docker-volumes", "kubernetes-probes-en"),
            ("nist-csf", "owasp-access-control"),
            ("sklearn-cross-validation", "pandas-groupby"),
            ("ftc-start-security", "w3c-non-text-content"),
            ("who-food-safety", "who-patient-safety"),
        ],
        "zh": [
            ("vue-reactivity-zh", "vue-computed-zh"),
            ("kubernetes-deployment-zh", "kubernetes-probes-zh"),
            ("aliyun-agent-zh", "aliyun-rag-zh"),
            ("labor-contract-law-zh", "civil-code-zh"),
            ("antimicrobial-use-zh", "infection-management-zh"),
            ("infection-management-zh", "hand-hygiene-zh"),
            ("food-safety-law-zh", "ecommerce-law-samr-zh"),
            ("accounting-basic-zh", "privacy-law-zh"),
            ("teachers-law-zh", "education-discipline-zh"),
            ("miit-standards-zh", "safety-production-law-zh"),
            ("patent-law-zh", "civil-code-zh"),
            ("privacy-law-zh", "ecommerce-law-samr-zh"),
        ],
    }
    for language, pairs in related_pairs.items():
        made = 0
        long_multi = 0
        seen_queries = {q["question"] for q in questions}
        for round_index in range(16):
            for left, right in pairs:
                firsts, seconds = chosen[left], chosen[right]
                if not firsts or not seconds:
                    continue
                first = firsts[round_index % len(firsts)]
                second = seconds[(round_index + len(seconds) // 2) % len(seconds)]
                parts = [first, second]
                kind = "multi_source_multi_intent"
                far = next(
                    (
                        pair
                        for pair in itertools.combinations(
                            sorted(firsts, key=lambda x: x["start"]), 2
                        )
                        if pair[1]["position"] - pair[0]["position"] >= 0.2
                        and pair[1]["start"] - pair[0]["end"] >= 800
                    ),
                    None,
                )
                if long_multi < 8 and far:
                    parts = [far[0], far[1], second]
                    kind = "long_span_multi_source"
                question = make_question(parts, kind, language, hashes)
                if question["question"] in seen_queries:
                    continue
                questions.append(question)
                seen_queries.add(question["question"])
                if kind == "long_span_multi_source":
                    long_multi += 1
                made += 1
                if made == 32:
                    break
            if made == 32:
                break
        if made < 32:
            raise ValueError(f"Insufficient cross-source questions for {language}")
        if long_multi < 8:
            raise ValueError(
                f"Insufficient long-span multi-source questions for {language}"
            )
    assert len(questions) == 400, len(questions)
    assign_source_disjoint_splits(questions, sources)
    for index, question in enumerate(questions, 1):
        question["id"] = f"PROF-{index:04d}"
    RESULT.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in questions),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "questions": len(questions),
                "languages": dict(Counter(q["language"] for q in questions)),
                "types": dict(Counter(q["task_type"] for q in questions)),
                "covered_sources": len({s for q in questions for s in q["source_ids"]}),
                "splits": dict(Counter(q["split"] for q in questions)),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
