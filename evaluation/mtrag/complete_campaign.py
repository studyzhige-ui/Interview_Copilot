"""One owner runs and resumes GPU stages sequentially, without polling live files."""

import subprocess
import sys


def main():
    steps = [
        ["evaluation.mtrag.embed_corpus", "--family", "bge"],
        ["evaluation.mtrag.run", "dense", "--family", "bge"],
        ["evaluation.mtrag.run", "rerank", "--family", "bge"],
        ["evaluation.mtrag.report"],
    ]
    for step in steps:
        print("START", " ".join(step), flush=True)
        subprocess.run([sys.executable, "-m", *step], check=True)
        print("FINISHED", " ".join(step), flush=True)


if __name__ == "__main__":
    main()
