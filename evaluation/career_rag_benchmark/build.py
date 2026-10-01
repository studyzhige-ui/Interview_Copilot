"""Build a bilingual occupational RAG candidate set from original sources."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/evaluation/career_rag_benchmark"
RAW = OUT / "raw"
INDEX = "https://chinajob.mohrss.gov.cn/zbzl/zdhd/hlwzyzd/zyhx/"
ONET = "https://www.onetcenter.org/dl_files/database/db_31_0_csv/"
ENGLISH_TITLES = (
    "Software Developers",
    "Registered Nurses",
    "Accountants and Auditors",
    "Lawyers",
    "Civil Engineers",
    "Elementary School Teachers, Except Special Education",
    "Market Research Analysts and Marketing Specialists",
    "Human Resources Specialists",
    "Pharmacists",
    "Logisticians",
    "Graphic Designers",
    "Construction Managers",
    "Food Service Managers",
    "Information Security Analysts",
    "Data Scientists",
    "Mechanical Engineers",
    "Sales Managers",
    "Child, Family, and School Social Workers",
    "Web Developers",
    "Environmental Engineers",
)
FIELDS = (
    ("职业定义", "这份职业画像如何定义“{title}”？"),
    ("下设工种", "“{title}”下设哪些工种？"),
    ("招聘岗位名称", "“{title}”常见的招聘岗位名称有哪些？"),
    ("学历要求", "“{title}”的普通受教育程度要求是什么？"),
    ("职业能力特征", "职业画像对“{title}”的能力特征有什么描述？"),
    ("相关专业", "职业画像列出哪些与“{title}”相关的专业？"),
    ("技能等级", "“{title}”设置了哪些技能等级？"),
    ("工作环境", "“{title}”通常在什么工作环境中工作？"),
    ("相关职业", "职业画像提到哪些与“{title}”相关的职业？"),
    ("专家观点", "职业指导专家如何评价“{title}”的就业前景？"),
)
LABELS = [x[0] for x in FIELDS] + ["职业名称", "主要工作任务"]


def fetch(url: str, path: Path) -> bytes:
    if path.exists() and path.stat().st_size:
        return path.read_bytes()
    request = urllib.request.Request(
        url, headers={"User-Agent": "CareerRAGBenchmark/0.1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = response.read()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def split_for(index: int, count: int) -> str:
    # Every occupation belongs to exactly one split. Counts are fixed by source language.
    if index < round(count * 0.6):
        return "dev"
    if index < round(count * 0.8):
        return "calibration"
    return "test"


def chinese_sources() -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for page in ("index.shtml", "index_2.shtml"):
        html = fetch(INDEX + page, RAW / ("china_index_" + page)).decode("utf-8")
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if re.fullmatch(r"/c/2022-\d\d-\d\d/\d+\.shtml", href):
                pair = (
                    link.get_text(" ", strip=True),
                    urllib.parse.urljoin(INDEX, href),
                )
                if pair not in links:
                    links.append(pair)
    return links


def article_text(html: bytes) -> str:
    soup = BeautifulSoup(html.decode("utf-8"), "html.parser")
    article = soup.select_one("div.detail_article")
    if article is None:
        raise ValueError("Chinese source has no detail_article")
    return re.sub(r"\s+", " ", article.get_text(" ", strip=True)).strip()


def field_value(text: str, label: str) -> str | None:
    next_labels = "|".join(re.escape(x) for x in LABELS if x != label)
    match = re.search(
        rf"{re.escape(label)}\s*[：:]\s*(.+?)(?=(?:{next_labels})\s*[：:]|$)", text
    )
    return match.group(1).strip() if match else None


def chinese_items(title: str, text: str) -> list[tuple[str, str, str]]:
    result: list[tuple[str, str, str]] = []
    code = re.search(r"职业编码\s*[：:]?\s*([0-9-]{8,})", text)
    if code:
        result.append((f"“{title}”的职业编码是什么？", code.group(1), "code"))
    for label, template in FIELDS:
        value = field_value(text, label)
        if value and value != "无" and len(value) <= 900:
            result.append((template.format(title=title), value, "profile_field"))
    tasks = field_value(text, "主要工作任务") or ""
    task_parts = [
        part.strip(" ;； ")
        for part in re.split(r"(?<!\d)\d{1,2}[.．、]\s*", tasks)
        if part.strip(" ;； ")
    ]
    for number, task in enumerate(task_parts, 1):
        if len(task) < 12:
            continue
        anchor = re.sub(r"[，,；;].*", "", task)[:14]
        question = f"根据“{title}”职业画像，涉及“{anchor}”的工作任务具体是什么？"
        if any(existing[0] == question for existing in result):
            anchor = task[:28].rstrip("，,；;。.")
            question = f"根据“{title}”职业画像，涉及“{anchor}”的工作任务具体是什么？"
        if any(existing[0] == question for existing in result):
            question = f"根据“{title}”职业画像，第{number}项工作任务具体是什么？"
        result.append((question, task, "task"))
    return result


def english_items(
    title: str, description: str, tasks: list[str]
) -> list[tuple[str, str, str]]:
    result = [
        (f"How does O*NET define the work of {title}?", description, "definition")
    ]
    seen: set[str] = set()
    trailing = {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "their",
        "to",
        "with",
    }
    second_verbs = {
        "analyze",
        "assess",
        "coordinate",
        "create",
        "develop",
        "evaluate",
        "identify",
        "manage",
        "monitor",
        "plan",
        "prepare",
        "provide",
        "recommend",
        "review",
        "report",
        "use",
    }
    for task in tasks:
        words = re.findall(r"[A-Za-z][A-Za-z'-]*", task)
        if len(words) < 8 or len(task) > 600:
            continue
        # Use the first noun-oriented clause as a topical cue, keeping ordinary
        # phrasing while avoiding a copy of the complete statement.
        lead = re.split(r"[,;]", task, maxsplit=1)[0]
        content = re.findall(r"[A-Za-z][A-Za-z'-]*", lead)[1:8]
        for position in range(2, len(content) - 1):
            if (
                content[position].lower() == "and"
                and content[position + 1].lower() in second_verbs
            ):
                content = content[:position]
                break
        content = content[:6]
        while content and content[0].lower() in {"and", "or"}:
            content.pop(0)
        while content and content[-1].lower() in trailing:
            content.pop()
        anchor = " ".join(content).lower()
        if anchor in seen:
            continue
        seen.add(anchor)
        result.append(
            (
                f"In the O*NET profile for {title}, what responsibility concerns {anchor}?",
                task,
                "task",
            )
        )
        if len(result) == 10:
            break
    return result


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    lock_path = OUT / "sources.jsonl"
    previous = None
    if lock_path.exists():
        previous = [
            json.loads(line)
            for line in lock_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    corpus: list[dict] = []
    queries: list[dict] = []
    answers: list[dict] = []
    sources: list[dict] = []
    qrels: dict[str, list[tuple[str, str]]] = defaultdict(list)
    definitions: dict[str, str] = {}

    def add_source(
        doc_id: str,
        title: str,
        language: str,
        url: str,
        filename: str,
        raw: bytes,
        text: str,
        additional_files: list[dict] | None = None,
    ) -> None:
        sources.append(
            {
                "source_id": doc_id,
                "title": title,
                "language": language,
                "files": [
                    {
                        "url": url,
                        "file": filename,
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
                ]
                + (additional_files or []),
            }
        )
        corpus.append(
            {
                "_id": doc_id,
                "title": title,
                "text": text,
                "source_id": doc_id,
                "language": language,
            }
        )

    def add_questions(
        doc_id: str,
        title: str,
        language: str,
        split: str,
        text: str,
        items: list[tuple[str, str, str]],
        limit: int,
    ) -> None:
        if len(items) < limit:
            raise ValueError(
                f"Only {len(items)} candidate items for {title}; need {limit}"
            )
        for index, (question, answer, kind) in enumerate(items[:limit], 1):
            start = text.find(answer)
            if start < 0:
                raise ValueError(
                    f"Answer is absent from source: {title}: {answer[:40]}"
                )
            qid = f"{doc_id}-q{index:02d}"
            queries.append(
                {
                    "_id": qid,
                    "text": question,
                    "language": language,
                    "source_language": language,
                    "occupation": title,
                    "split_group": doc_id,
                    "split": split,
                    "task_type": kind,
                }
            )
            answers.append(
                {
                    "query_id": qid,
                    "answer": answer,
                    "answerability": "answerable",
                    "evidence": [
                        {
                            "corpus_id": doc_id,
                            "start": start,
                            "end": start + len(answer),
                        }
                    ],
                    "review_status": "programmatic_candidate",
                }
            )
            qrels[split].append((qid, doc_id))

    zh = chinese_sources()
    if len(zh) != 12:
        raise ValueError(f"Expected 12 original Chinese job profiles, found {len(zh)}")
    for i, (title, url) in enumerate(zh):
        doc_id = f"zh-occ-{i + 1:02d}"
        filename = f"{doc_id}.html"
        raw = fetch(url, RAW / filename)
        text = article_text(raw)
        add_source(doc_id, title, "zh", url, filename, raw, text)
        definitions[doc_id] = field_value(text, "职业定义") or ""
        items = chinese_items(title, text)
        add_questions(
            doc_id, title, "zh", split_for(i, len(zh)), text, items, len(items)
        )

    onet_files = ("occupation_data.csv", "task_statements.csv")
    onet_raw = {name: fetch(ONET + name, RAW / name) for name in onet_files}
    occupations = {
        row["Title"]: row
        for row in csv.DictReader(
            onet_raw["occupation_data.csv"].decode("utf-8-sig").splitlines()
        )
    }
    tasks_by_code: dict[str, list[str]] = defaultdict(list)
    for row in csv.DictReader(
        onet_raw["task_statements.csv"].decode("utf-8-sig").splitlines()
    ):
        if row["Task Type"] == "Core":
            tasks_by_code[row["O*NET-SOC Code"]].append(row["Task"])
    for i, title in enumerate(ENGLISH_TITLES):
        row = occupations[title]
        code = row["O*NET-SOC Code"]
        doc_id = f"en-onet-{code}"
        items = english_items(title, row["Description"], tasks_by_code[code])
        text = (
            f"O*NET-SOC Code: {code}\nTitle: {title}\nDescription: {row['Description']}\n"
            + "\n".join(f"Task: {task}" for task in tasks_by_code[code])
        )
        definitions[doc_id] = row["Description"]
        add_source(
            doc_id,
            title,
            "en",
            ONET + "occupation_data.csv",
            "occupation_data.csv",
            onet_raw["occupation_data.csv"],
            text,
            [
                {
                    "url": ONET + "task_statements.csv",
                    "file": "task_statements.csv",
                    "sha256": hashlib.sha256(
                        onet_raw["task_statements.csv"]
                    ).hexdigest(),
                }
            ],
        )
        add_questions(
            doc_id, title, "en", split_for(i, len(ENGLISH_TITLES)), text, items, 10
        )

    by_id = {row["_id"]: row for row in corpus}
    by_title = {row["title"]: row["_id"] for row in corpus}
    zh_pairs = [(0, 1), (3, 4), (5, 6), (7, 8), (10, 11)]
    en_pairs = [
        (0, 10),
        (1, 8),
        (2, 3),
        (4, 11),
        (6, 7),
        (12, 15),
        (13, 14),
        (16, 17),
        (18, 19),
    ]
    for language, pairs, titles in (
        ("zh", zh_pairs, [title for title, _ in zh]),
        ("en", en_pairs, list(ENGLISH_TITLES)),
    ):
        for index, (left_index, right_index) in enumerate(pairs, 1):
            left_title, right_title = titles[left_index], titles[right_index]
            left, right = by_title[left_title], by_title[right_title]
            left_split = split_for(left_index, len(titles))
            if left_split != split_for(right_index, len(titles)):
                raise ValueError("Comparison crosses split boundary")
            qid = f"{language}-compare-{index:02d}"
            question = (
                f"根据职业定义，“{left_title}”与“{right_title}”的工作范围有何不同？"
                if language == "zh"
                else f"How do the defined scopes of work differ between {left_title} and {right_title}?"
            )
            answer = f"{left_title}: {definitions[left]}\n{right_title}: {definitions[right]}"
            evidence = []
            for doc_id in (left, right):
                phrase = definitions[doc_id]
                start = by_id[doc_id]["text"].find(phrase)
                if start < 0:
                    raise ValueError(f"Missing comparison evidence: {doc_id}")
                evidence.append(
                    {
                        "corpus_id": doc_id,
                        "start": start,
                        "end": start + len(phrase),
                        "text": phrase,
                    }
                )
                qrels[left_split].append((qid, doc_id))
            queries.append(
                {
                    "_id": qid,
                    "text": question,
                    "language": language,
                    "source_language": language,
                    "occupation": [left_title, right_title],
                    "split_group": left,
                    "split": left_split,
                    "task_type": "comparison",
                }
            )
            answers.append(
                {
                    "query_id": qid,
                    "answer": answer,
                    "answerability": "answerable",
                    "evidence": evidence,
                    "review_status": "programmatic_candidate",
                }
            )

    if previous is not None and previous != sources:
        raise ValueError(
            "Source snapshot differs from locked sources.jsonl; review before refreshing"
        )
    write_jsonl(OUT / "corpus.jsonl", corpus)
    write_jsonl(OUT / "queries.jsonl", queries)
    write_jsonl(OUT / "answers.jsonl", answers)
    write_jsonl(OUT / "sources.jsonl", sources)
    for split, rows in qrels.items():
        path = OUT / "qrels" / f"{split}.tsv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "query-id\tcorpus-id\tscore\n"
            + "".join(f"{qid}\t{doc_id}\t1\n" for qid, doc_id in rows),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "sources": len(sources),
                "queries": len(queries),
                "languages": {
                    language: sum(q["language"] == language for q in queries)
                    for language in ("zh", "en")
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
