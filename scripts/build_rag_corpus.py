import os
import re
import json
import urllib.request
import urllib.error
import time

# Define the targets catalog with corrected and verified URLs
TARGETS = [
    # 1. Official Technical Documents (30 documents)
    {
        "filename": "openai-prompt-engineering.md",
        "title": "OpenAI Prompt Engineering Principles",
        "category": "official_doc",
        "topic": "llm",
        "language": "en",
        "date": "2024-03",
        "license": "MIT",
        "urls": [
            "https://raw.githubusercontent.com/dair-ai/Prompt-Engineering-Guide/main/guides/prompts-intro.md"
        ]
    },
    {
        "filename": "huggingface-transformers-quicktour-en.md",
        "title": "Hugging Face Transformers Quicktour (EN)",
        "category": "official_doc",
        "topic": "framework",
        "language": "en",
        "date": "2024-05",
        "license": "Apache-2.0",
        "urls": [
            "https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/en/quicktour.md"
        ]
    },
    {
        "filename": "huggingface-transformers-quicktour-zh.md",
        "title": "Hugging Face Transformers Quicktour (ZH)",
        "category": "official_doc",
        "topic": "framework",
        "language": "zh",
        "date": "2024-05",
        "license": "Apache-2.0",
        "urls": [
            "https://raw.githubusercontent.com/huggingface/transformers/main/docs/source/zh/quicktour.md"
        ]
    },
    {
        "filename": "llamaindex-concepts.md",
        "title": "LlamaIndex High-Level Concepts",
        "category": "official_doc",
        "topic": "rag",
        "language": "en",
        "date": "2024-06",
        "license": "MIT",
        "urls": [
            "https://raw.githubusercontent.com/run-llama/llama_index/main/docs/src/content/docs/framework/getting_started/concepts.mdx"
        ]
    },
    {
        "filename": "langchain-rag-tutorial.md",
        "title": "LangChain RAG Tutorial (EN)",
        "category": "official_doc",
        "topic": "agent",
        "language": "en",
        "date": "2024-08",
        "license": "MIT",
        "urls": [
            "https://raw.githubusercontent.com/langchain-ai/docs/main/src/oss/langchain/rag.mdx"
        ]
    },
    {
        "filename": "react-thinking-in-react-en.md",
        "title": "Thinking in React (EN)",
        "category": "official_doc",
        "topic": "framework",
        "language": "en",
        "date": "2024-02",
        "license": "CC-BY-4.0",
        "urls": [
            "https://raw.githubusercontent.com/reactjs/react.dev/main/src/content/learn/thinking-in-react.md"
        ]
    },
    {
        "filename": "react-thinking-in-react-zh.md",
        "title": "Thinking in React (ZH)",
        "category": "official_doc",
        "topic": "framework",
        "language": "zh",
        "date": "2024-02",
        "license": "CC-BY-4.0",
        "urls": [
            "https://raw.githubusercontent.com/reactjs/zh-hans.react.dev/main/src/content/learn/thinking-in-react.md"
        ]
    },
    {
        "filename": "vue-introduction-en.md",
        "title": "Vue.js Introduction (EN)",
        "category": "official_doc",
        "topic": "framework",
        "language": "en",
        "date": "2024-01",
        "license": "MIT",
        "urls": [
            "https://raw.githubusercontent.com/vuejs/docs/main/src/guide/introduction.md"
        ]
    },
    {
        "filename": "vue-introduction-zh.md",
        "title": "Vue.js Introduction (ZH)",
        "category": "official_doc",
        "topic": "framework",
        "language": "zh",
        "date": "2024-01",
        "license": "MIT",
        "urls": [
            "https://raw.githubusercontent.com/vuejs-translations/docs-zh-cn/main/src/guide/introduction.md"
        ]
    },
    {
        "filename": "fastapi-tutorial-intro-en.md",
        "title": "FastAPI Tutorial - User Guide Intro (EN)",
        "category": "official_doc",
        "topic": "framework",
        "language": "en",
        "date": "2024-04",
        "license": "MIT",
        "urls": [
            "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/en/docs/tutorial/index.md"
        ]
    },
    {
        "filename": "fastapi-tutorial-intro-zh.md",
        "title": "FastAPI Tutorial - User Guide Intro (ZH)",
        "category": "official_doc",
        "topic": "framework",
        "language": "zh",
        "date": "2024-04",
        "license": "MIT",
        "urls": [
            "https://raw.githubusercontent.com/fastapi/fastapi/master/docs/zh/docs/tutorial/index.md"
        ]
    },
    {
        "filename": "django-tutorial01.txt",
        "title": "Django Tutorial Part 1 (EN)",
        "category": "official_doc",
        "topic": "framework",
        "language": "en",
        "date": "2024-03",
        "license": "BSD-3-Clause",
        "urls": [
            "https://raw.githubusercontent.com/django/django/main/docs/intro/tutorial01.txt"
        ]
    },
    {
        "filename": "django-models-en.txt",
        "title": "Django Models Guide",
        "category": "official_doc",
        "topic": "framework",
        "language": "en",
        "date": "2024-03",
        "license": "BSD-3-Clause",
        "urls": [
            "https://raw.githubusercontent.com/django/django/main/docs/topics/db/models.txt"
        ]
    },
    {
        "filename": "python-controlflow-en.rst",
        "title": "Python Tutorial - More Control Flow Tools (EN)",
        "category": "official_doc",
        "topic": "language",
        "language": "en",
        "date": "2024-05",
        "license": "PSF",
        "urls": [
            "https://raw.githubusercontent.com/python/cpython/main/Doc/tutorial/controlflow.rst"
        ]
    },
    {
        "filename": "typescript-handbook-basic-types-en.md",
        "title": "TypeScript Handbook - Basic Types (EN)",
        "category": "official_doc",
        "topic": "language",
        "language": "en",
        "date": "2024-02",
        "license": "Apache-2.0",
        "urls": [
            "https://raw.githubusercontent.com/microsoft/TypeScript-Handbook/master/pages/Basic%20Types.md"
        ]
    },
    {
        "filename": "go-effective-go.html",
        "title": "Effective Go (EN)",
        "category": "official_doc",
        "topic": "language",
        "language": "en",
        "date": "2024-03",
        "license": "BSD-3-Clause",
        "urls": [
            "https://go.dev/doc/effective_go"
        ]
    },
    {
        "filename": "rust-ownership-en.md",
        "title": "The Rust Programming Language - Ownership (EN)",
        "category": "official_doc",
        "topic": "language",
        "language": "en",
        "date": "2024-06",
        "license": "MIT OR Apache-2.0",
        "urls": [
            "https://raw.githubusercontent.com/rust-lang/book/main/src/ch04-00-understanding-ownership.md"
        ]
    },
    {
        "filename": "rust-ownership-zh.md",
        "title": "The Rust Programming Language - Ownership (ZH)",
        "category": "official_doc",
        "topic": "language",
        "language": "zh",
        "date": "2024-06",
        "license": "MIT OR Apache-2.0",
        "urls": [
            "https://raw.githubusercontent.com/KaiserY/trpl-zh-cn/master/src/ch04-00-understanding-ownership.md"
        ]
    },
    {
        "filename": "kubernetes-nodes-en.md",
        "title": "Kubernetes Concepts - Nodes (EN)",
        "category": "official_doc",
        "topic": "infra",
        "language": "en",
        "date": "2024-07",
        "license": "CC-BY-4.0",
        "urls": [
            "https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/architecture/nodes.md"
        ]
    },
    {
        "filename": "kubernetes-nodes-zh.md",
        "title": "Kubernetes Concepts - Nodes (ZH)",
        "category": "official_doc",
        "topic": "infra",
        "language": "zh",
        "date": "2024-07",
        "license": "CC-BY-4.0",
        "urls": [
            "https://raw.githubusercontent.com/kubernetes/website/main/content/zh-cn/docs/concepts/architecture/nodes.md"
        ]
    },
    {
        "filename": "kubernetes-pods-en.md",
        "title": "Kubernetes Concepts - Pod Lifecycle",
        "category": "official_doc",
        "topic": "infra",
        "language": "en",
        "date": "2024-07",
        "license": "CC-BY-4.0",
        "urls": [
            "https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/workloads/pods/pod-lifecycle.md"
        ]
    },
    {
        "filename": "docker-overview-en.md",
        "title": "Docker Overview (EN)",
        "category": "official_doc",
        "topic": "infra",
        "language": "en",
        "date": "2024-05",
        "license": "Apache-2.0",
        "urls": [
            "https://raw.githubusercontent.com/docker/docs/main/content/manuals/engine/_index.md"
        ]
    },
    {
        "filename": "redis-transactions-en.md",
        "title": "Redis Transactions (EN)",
        "category": "official_doc",
        "topic": "database",
        "language": "en",
        "date": "2024-02",
        "license": "CC-BY-SA-4.0",
        "urls": [
            "https://raw.githubusercontent.com/redis/docs/main/content/develop/using-commands/transactions.md"
        ]
    },
    {
        "filename": "redis-persistence-en.md",
        "title": "Redis Persistence (EN)",
        "category": "official_doc",
        "topic": "database",
        "language": "en",
        "date": "2024-02",
        "license": "CC-BY-SA-4.0",
        "urls": [
            "https://raw.githubusercontent.com/redis/docs/main/content/operate/oss_and_stack/management/persistence.md"
        ]
    },
    {
        "filename": "milvus-intro-en.md",
        "title": "Milvus Introduction (EN)",
        "category": "official_doc",
        "topic": "database",
        "language": "en",
        "date": "2024-04",
        "license": "Apache-2.0",
        "urls": [
            "https://raw.githubusercontent.com/milvus-io/milvus-docs/v2.4.x/site/en/home/home.md"
        ]
    },
    {
        "filename": "milvus-intro-zh.md",
        "title": "Milvus Introduction (ZH)",
        "category": "official_doc",
        "topic": "database",
        "language": "zh",
        "date": "2024-04",
        "license": "Apache-2.0",
        "urls": [
            "https://raw.githubusercontent.com/milvus-io/milvus/master/README_CN.md"
        ]
    },
    {
        "filename": "kafka-design-en.md",
        "title": "Apache Kafka Design (EN)",
        "category": "official_doc",
        "topic": "database",
        "language": "en",
        "date": "2024-03",
        "license": "Apache-2.0",
        "urls": [
            "https://raw.githubusercontent.com/apache/kafka/trunk/docs/design/design.md"
        ]
    },
    {
        "filename": "pytorch-autograd-notes.md",
        "title": "PyTorch Autograd Notes (EN)",
        "category": "official_doc",
        "topic": "framework",
        "language": "en",
        "date": "2024-06",
        "license": "BSD-3-Clause",
        "urls": [
            "https://raw.githubusercontent.com/pytorch/pytorch/main/docs/source/notes/autograd.md"
        ]
    },
    {
        "filename": "pytorch-serialization-notes.md",
        "title": "PyTorch Serialization Notes (EN)",
        "category": "official_doc",
        "topic": "framework",
        "language": "en",
        "date": "2024-06",
        "license": "BSD-3-Clause",
        "urls": [
            "https://raw.githubusercontent.com/pytorch/pytorch/main/docs/source/notes/serialization.md"
        ]
    },
    {
        "filename": "postgresql-mvcc-en.html",
        "title": "Postgres MVCC (EN)",
        "category": "official_doc",
        "topic": "database",
        "language": "en",
        "date": "2024-03",
        "license": "PostgreSQL License",
        "urls": [
            "https://raw.githubusercontent.com/postgres/postgres/master/doc/src/sgml/mvcc.sgml"
        ]
    },

    # 2. Classic Papers (8 papers)
    {
        "filename": "attention-is-all-you-need.pdf",
        "title": "Attention Is All You Need",
        "category": "paper",
        "topic": "llm",
        "language": "en",
        "date": "2017-06",
        "license": "arXiv open access",
        "urls": [
            "https://arxiv.org/pdf/1706.03762.pdf"
        ]
    },
    {
        "filename": "bert-pretraining-transformers.pdf",
        "title": "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        "category": "paper",
        "topic": "llm",
        "language": "en",
        "date": "2018-10",
        "license": "arXiv open access",
        "urls": [
            "https://arxiv.org/pdf/1810.04805.pdf"
        ]
    },
    {
        "filename": "resnet-image-recognition.pdf",
        "title": "Deep Residual Learning for Image Recognition",
        "category": "paper",
        "topic": "framework",
        "language": "en",
        "date": "2015-12",
        "license": "arXiv open access",
        "urls": [
            "https://arxiv.org/pdf/1512.03385.pdf"
        ]
    },
    {
        "filename": "adam-optimization.pdf",
        "title": "Adam: A Method for Stochastic Optimization",
        "category": "paper",
        "topic": "framework",
        "language": "en",
        "date": "2014-12",
        "license": "arXiv open access",
        "urls": [
            "https://arxiv.org/pdf/1412.6980.pdf"
        ]
    },
    {
        "filename": "rag-knowledge-intensive-nlp.pdf",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "category": "paper",
        "topic": "rag",
        "language": "en",
        "date": "2020-05",
        "license": "arXiv open access",
        "urls": [
            "https://arxiv.org/pdf/2005.11401.pdf"
        ]
    },
    {
        "filename": "react-reasoning-acting.pdf",
        "title": "ReAct: Synergizing Reasoning and Acting in Language Models",
        "category": "paper",
        "topic": "agent",
        "language": "en",
        "date": "2022-10",
        "license": "arXiv open access",
        "urls": [
            "https://arxiv.org/pdf/2210.03629.pdf"
        ]
    },
    {
        "filename": "flash-attention-io-aware.pdf",
        "title": "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
        "category": "paper",
        "topic": "llm",
        "language": "en",
        "date": "2022-05",
        "license": "arXiv open access",
        "urls": [
            "https://arxiv.org/pdf/2205.14135.pdf"
        ]
    },
    {
        "filename": "word2vec-vector-representation.pdf",
        "title": "Efficient Estimation of Word Representations in Vector Space",
        "category": "paper",
        "topic": "llm",
        "language": "en",
        "date": "2013-01",
        "license": "arXiv open access",
        "urls": [
            "https://arxiv.org/pdf/1301.3781.pdf"
        ]
    },

    # 3. QA Banks (6 documents)
    {
        "filename": "system-design-primer-pastebin-en.md",
        "title": "Donne Martin Pastebin Design QA",
        "category": "qa_bank",
        "topic": "system_design",
        "language": "en",
        "date": "2024-01",
        "license": "CC-BY-4.0",
        "urls": [
            "https://raw.githubusercontent.com/donnemartin/system-design-primer/master/solutions/system_design/pastebin/README.md"
        ]
    },
    {
        "filename": "system-design-primer-scaling-en.md",
        "title": "Donne Martin AWS Scaling QA",
        "category": "qa_bank",
        "topic": "system_design",
        "language": "en",
        "date": "2024-01",
        "license": "CC-BY-4.0",
        "urls": [
            "https://raw.githubusercontent.com/donnemartin/system-design-primer/master/solutions/system_design/scaling_aws/README.md"
        ]
    },
    {
        "filename": "python-interview-questions-zh.md",
        "title": "Python Interview QA bank (ZH)",
        "category": "qa_bank",
        "topic": "language",
        "language": "zh",
        "date": "2024-03",
        "license": "Public Domain",
        "urls": [
            "https://raw.githubusercontent.com/jackfrued/Python-100-Days/master/Day91-100/99.%E9%9D%A2%E8%AF%95%E4%B8%AD%E7%9A%84%E5%85%AC%E5%85%B1%E9%97%AE%E9%A2%98.md"
        ]
    },
    {
        "filename": "javaguide-basic-questions-zh.md",
        "title": "JavaGuide Basic QA (ZH)",
        "category": "qa_bank",
        "topic": "language",
        "language": "zh",
        "date": "2024-05",
        "license": "CC-BY-NC-SA-4.0",
        "urls": [
            "https://raw.githubusercontent.com/Snailclimb/JavaGuide/main/docs/java/basis/java-basic-questions-01.md"
        ]
    },
    {
        "filename": "go-interview-questions-zh.md",
        "title": "Golang Interview QA (ZH)",
        "category": "qa_bank",
        "topic": "language",
        "language": "zh",
        "date": "2024-02",
        "license": "MIT",
        "urls": [
            "https://raw.githubusercontent.com/iswbm/golang-interview/master/README.md"
        ]
    },
    {
        "filename": "database-mysql-questions-zh.md",
        "title": "JavaGuide MySQL QA (ZH)",
        "category": "qa_bank",
        "topic": "database",
        "language": "zh",
        "date": "2024-05",
        "license": "CC-BY-NC-SA-4.0",
        "urls": [
            "https://raw.githubusercontent.com/Snailclimb/JavaGuide/main/docs/database/mysql/mysql-questions-01.md"
        ]
    }
]

# Set absolute path for the output corpus directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, '..', 'rag_eval_corpus'))

def try_download(urls):
    """
    Tries to download the file from a list of alternate URLs.
    Includes retries and custom User-Agent.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    for url in urls:
        for attempt in range(3):
            try:
                print(f"Downloading from {url} (Attempt {attempt + 1})...")
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=25) as response:
                    if response.status == 200:
                        return response.read(), url
            except Exception as e:
                print(f"  Attempt {attempt + 1} failed: {e}")
                time.sleep(2)
    raise Exception(f"Failed to download from all URL alternatives: {urls}")

def estimate_words(text):
    """
    Estimates words: counts English words (whitespace separated alpha-numeric)
    and Chinese characters (Unicode range).
    """
    # Count English words
    en_words = len(re.findall(r'[a-zA-Z0-9\-\']+', text))
    # Count Chinese characters
    zh_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    return en_words + zh_chars

def extract_text_from_pdf(filepath):
    """
    Extracts text from PDF file using PyMuPDF (fitz)
    """
    try:
        import fitz
        doc = fitz.open(filepath)
        text = ""
        for page in doc:
            text += page.get_text()
        return text
    except Exception as e:
        print(f"Error extracting PDF text: {e}")
        return ""

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Created directory: {OUTPUT_DIR}")

    manifest_path = os.path.join(OUTPUT_DIR, 'manifest.jsonl')
    manifest_records = []
    
    success_count = 0
    fail_count = 0

    for idx, target in enumerate(TARGETS, 1):
        filename = target["filename"]
        dest_path = os.path.join(OUTPUT_DIR, filename)
        
        print(f"\n[{idx}/{len(TARGETS)}] Processing: {filename}")
        
        try:
            content_bytes, used_url = try_download(target["urls"])
            
            # Save downloaded file
            with open(dest_path, 'wb') as f:
                f.write(content_bytes)
            print(f"  Saved to: {dest_path}")
            
            # Estimate word count
            word_count = 0
            if filename.endswith('.pdf'):
                # PDF: extract text and then count words
                pdf_text = extract_text_from_pdf(dest_path)
                word_count = estimate_words(pdf_text)
            else:
                # Text files: decode and estimate
                try:
                    text_content = content_bytes.decode('utf-8')
                except UnicodeDecodeError:
                    text_content = content_bytes.decode('gbk', errors='ignore')
                word_count = estimate_words(text_content)
                
            print(f"  Estimated words: {word_count}")
            
            # Record manifest entries
            manifest_records.append({
                "filename": filename,
                "title": target["title"],
                "source_url": used_url,
                "category": target["category"],
                "topic": target["topic"],
                "language": target["language"],
                "date": target["date"],
                "license": target["license"],
                "words_estimate": word_count
            })
            success_count += 1
            
        except Exception as e:
            print(f"  ERROR: Failed to process {filename}: {e}")
            fail_count += 1

    # Write manifest.jsonl
    with open(manifest_path, 'w', encoding='utf-8') as f:
        for record in manifest_records:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
            
    print(f"\nFinished! Success: {success_count}, Failed: {fail_count}")
    print(f"Manifest written to: {manifest_path}")

if __name__ == '__main__':
    main()
