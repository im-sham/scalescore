from scalescore.cli import build_parser
from scalescore.demo import _demo_dataset_path


def test_cli_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args([])

    assert args.dataset_path == "data"
    assert args.json is False


def test_demo_dataset_path_exists() -> None:
    path = _demo_dataset_path()
    assert path.exists()
