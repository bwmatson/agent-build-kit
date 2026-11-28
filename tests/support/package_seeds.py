"""Test support: the seeds the package-boundary scan assigns modules from, and its baseline.

Seeds are dotted module names relative to `agent_build_kit` (a module or a package). The baseline
is the set of `(importer, imported)` module pairs that cross a package boundary today; it may
only shrink.
"""

from agent_build_kit.model import Frozen


class Seeds(Frozen):
    core: frozenset[str]
    worker: frozenset[str]
    orchestrator: frozenset[str]


def seeds() -> Seeds:
    """The seeds from the design of `worker-stops-importing-the-orchestrator`."""
    return Seeds(
        core=frozenset(
            {
                "forges",
                "profiles",
                "sandboxes",
                "hooks",
                "runtimes",
                "orchestration",
                "graph.checkpointer",
                "serve.review",
                "split.select",
                "tracks.runner",
                "trackers.base",
                "trackers.config",
                "trackers.folders",
                "trackers.levels",
                "trackers.manual_parent",
                "trackers.pr_attach",
            }
        ),
        worker=frozenset(
            {"cli.worker", "graph", "pipeline.resolution_lane", "pipeline.verify", "worker_run"}
        ),
        orchestrator=frozenset(
            {
                "__main__",
                "cli",
                "serve",
                *(
                    f"trackers.{name}"
                    for name in (
                        "adopt_from_hold",
                        "apply",
                        "azure_devops",
                        "azure_probe",
                        "azure_work_item_models",
                        "backfill",
                        "field_reconcile",
                        "github",
                        "github_models",
                        "hand_built",
                        "hand_over",
                        "local",
                        "operations",
                        "poll",
                        "reconciler",
                        "report",
                        "resilient",
                        "start_decision",
                        "tick_step",
                        "wanted_board",
                    )
                ),
                "tracks",
                "notify",
                "split",
                "config_migrate",
                "config_migrate_machine",
                "config_migrate_write",
                "machine_settings",
                "infra.docker",
                "infra.none",
                "init.research",
                "replay.hosts",
                "pipeline.admission",
                "pipeline.attach",
                "pipeline.consequences",
                "pipeline.events",
                "pipeline.gate",
                "pipeline.landing",
                "pipeline.outlines",
                "pipeline.plan_review",
                "pipeline.planner",
                "pipeline.planning_view",
                "pipeline.pr_reconcile",
                "pipeline.reorg_comparison",
                "pipeline.suite_shape",
            }
        ),
    )


def baseline() -> frozenset[tuple[str, str]]:
    """The imports that cross a boundary today, as `(importer, imported)` module names."""
    return frozenset(
        {
            ("cli.pipeline", "pipeline.resolution_lane"),
            ("cli.pipeline", "pipeline.verify"),
            ("serve.server", "graph.unit"),
        }
    )
