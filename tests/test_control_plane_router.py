from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ControlPlaneRouterTests(unittest.TestCase):
    def setUp(self):
        self.worker = (ROOT / "cloudflare-worker" / "src" / "index.js").read_text(encoding="utf-8")
        self.wrangler = (ROOT / "cloudflare-worker" / "wrangler.toml").read_text(encoding="utf-8")
        self.deploy = (ROOT / ".github" / "workflows" / "deploy-telegram-control-plane.yml").read_text(encoding="utf-8")

    def test_main_menu_and_callbacks_are_project_namespaced(self):
        for token in (
            'callback_data: "menu:spain"',
            'callback_data: "menu:international"',
            'callback_data: `${project.key}:run`',
            'callback_data: `${project.key}:status`',
            'callback_data: `${project.key}:today`',
            'callback_data: `${project.key}:file`',
        ):
            self.assertIn(token, self.worker)

    def test_legacy_generic_actions_select_project_instead_of_defaulting_to_spain(self):
        self.assertIn('actionSelectorKeyboard(normalized)', self.worker)
        self.assertIn('generic actions never silently default to Spain', self.worker)

    def test_excel_names_make_project_identity_explicit(self):
        self.assertIn('spain_job_search_report.xlsx', self.worker)
        self.assertIn('international_academic_job_report.xlsx', self.worker)
        self.assertIn('Spain — Latest job-search report', self.worker)
        self.assertIn('International — Latest academic job report', self.worker)

    def test_international_manual_run_is_routine_not_bootstrap_or_release_acceptance(self):
        self.assertIn('bootstrap_production: false', self.worker)
        self.assertIn('release_acceptance: false', self.worker)
        self.assertIn('send_telegram: false', self.worker)
        self.assertNotIn('send_telegram: true', self.worker)
        self.assertIn('max_jobs_per_source: "all"', self.worker)

    def test_cloudflare_routes_both_projects_with_madrid_time(self):
        self.assertIn('timeZone: "Europe/Madrid"', self.worker)
        self.assertIn('scheduledProject(controller)', self.worker)
        self.assertIn('projects(env)[key]', self.worker)
        self.assertIn('crons = ["17 3 * * *", "0 4 * * *", "0 5 * * *"]', self.wrangler)

    def test_worker_has_distinct_r2_bindings(self):
        self.assertIn('binding = "REPORTS_SPAIN"', self.wrangler)
        self.assertIn('binding = "REPORTS_INTERNATIONAL"', self.wrangler)
        self.assertIn('control-plane/latest/manifest.json', self.worker)
        self.assertIn('CONTROL_PLANE_REPORT_POINTER_V1.0.0', self.worker)

    def test_telegram_registered_commands_are_clean_top_level_navigation(self):
        self.assertIn("{'command': 'menu'", self.deploy)
        self.assertIn("{'command': 'spain'", self.deploy)
        self.assertIn("{'command': 'international'", self.deploy)
        self.assertIn("{'command': 'help'", self.deploy)
        for old in ("{'command': 'run'", "{'command': 'status'", "{'command': 'today'", "{'command': 'file'"):
            self.assertNotIn(old, self.deploy)

    def test_deploy_readiness_requires_both_projects(self):
        self.assertIn('Spain GitHub + R2: verified', self.deploy)
        self.assertIn('International GitHub + R2: verified', self.deploy)
        self.assertIn('Verify GitHub token can read both production workflows', self.deploy)


if __name__ == "__main__":
    unittest.main()
