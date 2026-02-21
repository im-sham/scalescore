from __future__ import annotations

from pathlib import Path

from scalescore.core.assessment import run_assessment_from_csv


def _demo_dataset_path() -> Path:
    cwd_path = Path.cwd() / "data"
    if cwd_path.exists():
        return cwd_path

    project_root = Path(__file__).resolve().parents[2]
    fallback = project_root / "data"
    if fallback.exists():
        return fallback

    raise FileNotFoundError("Could not locate demo dataset directory named 'data'")


def main() -> None:
    dataset_path = _demo_dataset_path()
    report = run_assessment_from_csv(dataset_path)

    print("ScaleScore Demo")
    print(f"Dataset: {dataset_path}")
    print(f"Organization: {report.org_name} ({report.org_id})")
    print(f"Overall Score: {report.overall_score:.1f} ({report.overall_grade})")
    print(f"Constraints: {report.total_constraints}")
    print(f"Risks: {report.total_risks}")
    print(f"Recommendations: {report.total_recommendations}")

    if report.key_findings:
        print("\nKey Findings:")
        for finding in report.key_findings:
            print(f"- {finding}")


if __name__ == "__main__":
    main()
