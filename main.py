from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from config.settings import FilterSettings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GPS Journey Analyzer")
    parser.add_argument("paths", nargs="*", help="File hoặc thư mục Excel nạp khi khởi động")
    parser.add_argument("--analyze", nargs="+", metavar="PATH", help="Phân tích không mở GUI")
    parser.add_argument("--output", default="output/GPS_Journey_Analyzer_Report.xlsx")
    parser.add_argument("--mode", choices=["Conservative", "Balanced", "Aggressive"], default="Conservative")
    return parser


def cli_analyze(paths: list[str], output: str, mode: str) -> int:
    from core.pipeline import analyze_paths
    from reports.excel_exporter import export_report

    result = analyze_paths(paths, FilterSettings(mode=mode))
    target = export_report(result, output)
    print(result.daily.to_string(index=False))
    print("\nTổng:", result.totals)
    print("Báo cáo:", target)
    for line in result.logs:
        print("-", line)
    return 0


def main() -> int:
    args = build_parser().parse_args()
    if args.analyze:
        return cli_analyze(args.analyze, args.output, args.mode)
    from PySide6.QtWidgets import QApplication
    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("GPS Journey Analyzer")
    window = MainWindow(args.paths)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

