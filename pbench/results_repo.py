"""Optional git repo that receives results after every test.

Each `bench.py run` creates a fresh orphan branch named `<date>-<host>`, so
every run starts from an empty tree, as run-all.sh did. Installed tests,
crash reproducers and logs stay out of the repo: they're large and only
useful on the machine that made them.
"""

import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .config import Config
from .layout import Layout

# Copied from output_dir into the repo. Crash reproducers are summarized by
# crashes/index.tsv only.
SYNCED = ["run.json", "install-summary.tsv", "README.md", "data", "asm-diff",
          "test-results", "csv", "plots", "crashes/index.tsv"]
# Large or machine-local files inside the synced dirs. Inline remarks were
# kept out of the repo before as well.
IGNORED = ["inline-remarks.txt", "*.log", "status.json"]


def git(repo: Path, *args: str, check: bool = True) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=check)


class ResultsRepo:
    def __init__(self, cfg: Config, layout: Layout, push: bool):
        assert cfg.results_repo is not None
        self.repo = cfg.results_repo
        self.layout = layout
        self.push = push and cfg.results_repo_push
        stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        self.branch = f"{stamp}-{cfg.host}"

    def start(self) -> None:
        """Switch to a new, empty orphan branch."""
        git(self.repo, "checkout", "--orphan", self.branch)
        git(self.repo, "rm", "-rf", "-q", "--ignore-unmatch", ".")
        git(self.repo, "clean", "-fdq")

    def publish(self, message: str) -> None:
        for rel in SYNCED:
            src = self.layout.root / rel
            dst = self.repo / rel
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(*IGNORED))
            elif src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        git(self.repo, "add", "-A")
        staged = subprocess.run(["git", "-C", str(self.repo), "diff",
                                 "--cached", "--quiet"])
        if staged.returncode == 0:
            return  # nothing changed, e.g. every install of this test failed
        git(self.repo, "commit", "--no-gpg-sign", "-q", "-m", message)
        if self.push:
            git(self.repo, "push", "-f", "-q", "-u", "origin", self.branch)
