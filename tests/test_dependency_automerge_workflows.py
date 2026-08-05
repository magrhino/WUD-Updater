from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

from ruamel.yaml import YAML


ROOT = Path(__file__).resolve().parents[1]
PRIVILEGED_WORKFLOW = ROOT / ".github/workflows/dependency-automerge.yml"
CANDIDATE_WORKFLOW = ROOT / ".github/workflows/dependency-automerge-candidate.yml"


class DependencyAutomergeWorkflowTests(unittest.TestCase):
    @staticmethod
    def _workflow(path: Path) -> tuple[dict, str]:
        text = path.read_text(encoding="utf-8")
        return YAML(typ="safe").load(text), text

    @staticmethod
    def _provenance_program(text: str) -> str:
        match = re.search(
            r'--arg bot "\$(?:BOT|bot)" \\\n\s+\'([^\']+)\'',
            text,
        )
        if match is None:
            raise AssertionError("provenance jq program not found")
        return match.group(1)

    @staticmethod
    def _verified_commit(author: str) -> dict:
        return {
            "author": {"login": author},
            "committer": {"login": "web-flow"},
            "commit": {"verification": {"verified": True, "reason": "valid"}},
        }

    def _jq_accepts(self, program: str, pages: list[list[dict]]) -> bool:
        result = subprocess.run(
            ["jq", "-e", "--arg", "bot", "dependabot[bot]", program],
            input=json.dumps(pages),
            capture_output=True,
            check=False,
            text=True,
        )
        return result.returncode == 0

    def test_privileged_workflow_uses_verified_atomic_merge(self) -> None:
        workflow, text = self._workflow(PRIVILEGED_WORKFLOW)

        self.assertIn("workflow_run", workflow["on"])
        self.assertNotIn("pull_request_target", workflow["on"])
        self.assertNotIn("actions/checkout@", text)
        self.assertNotIn("gh pr review", text)
        self.assertNotIn("--auto", text)
        self.assertIn('"repos/$GH_REPO/pulls/$PR_NUMBER/merge"', text)
        self.assertIn('-f sha="$head_sha"', text)
        self.assertIn('gh pr checks "$PR_NUMBER"', text)

        program = self._provenance_program(text)
        valid = self._verified_commit("dependabot[bot]")
        self.assertTrue(self._jq_accepts(program, [[valid]]))
        self.assertFalse(self._jq_accepts(program, [[valid, valid]]))

    def test_candidate_workflow_is_read_only_and_verifies_bots(self) -> None:
        workflow, text = self._workflow(CANDIDATE_WORKFLOW)

        self.assertIn("pull_request_target", workflow["on"])
        self.assertTrue(
            all(permission == "read" for permission in workflow["permissions"].values())
        )
        self.assertNotIn("actions/checkout@", text)
        self.assertNotIn("secrets.", text)
        self.assertIn("dependabot/fetch-metadata@", text)
        self.assertIn("[.[][]] |", text)
        self.assertIn("length == 1", text)
        self.assertIn(".author.login == $bot", text)
        self.assertIn('.committer.login == "web-flow"', text)
        self.assertIn(".commit.verification.verified == true", text)
        self.assertIn('.commit.verification.reason == "valid"', text)
        self.assertIn(".actor.login // empty", text)

        privileged_text = PRIVILEGED_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("length == 1", privileged_text)
        self.assertIn(".author.login == $bot", privileged_text)
        self.assertIn('.committer.login == "web-flow"', privileged_text)

        program = self._provenance_program(text)
        valid = self._verified_commit("dependabot[bot]")
        collaborator = self._verified_commit("maintainer")
        self.assertTrue(self._jq_accepts(program, [[valid]]))
        self.assertFalse(self._jq_accepts(program, [[valid, collaborator]]))

    def test_renovate_marks_only_non_major_updates(self) -> None:
        config = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))
        rule = config["packageRules"][0]

        self.assertEqual(
            rule["matchUpdateTypes"], ["minor", "patch", "pin", "digest"]
        )
        self.assertEqual(rule["addLabels"], ["automerge"])
        self.assertNotIn("automerge", rule)


if __name__ == "__main__":
    unittest.main()
