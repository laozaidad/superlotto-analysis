"""技能入口及引用文件的发布契约，开发环境需要PyYAML。"""
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/superlotto"


class SkillContractTests(unittest.TestCase):
    def test_frontmatter_and_display_name(self):
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        frontmatter = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual(frontmatter["name"], "superlotto")
        self.assertTrue(frontmatter["description"])
        self.assertIn("大乐透选号分析", text)
        interface = yaml.safe_load((SKILL / "agents/openai.yaml").read_text())["interface"]
        self.assertEqual(interface["display_name"], "大乐透选号分析")
        self.assertIn("$superlotto", interface["default_prompt"])

    def test_required_portable_resources(self):
        for name in ("scripts/run_skill.py", "scripts/model.py", "scripts/fetch_data.py",
                     "scripts/run_research.py", "scripts/research.py", "scripts/conditional_core.py",
                     "references/data-schema.md", "references/methodology.md", "references/research.md"):
            self.assertTrue((SKILL / name).is_file(), name)
        for path in SKILL.rglob("*"):
            if path.suffix in {".md", ".py", ".yaml"}:
                self.assertNotIn("/Users/", path.read_text(encoding="utf-8"), str(path))


if __name__ == "__main__":
    unittest.main()
