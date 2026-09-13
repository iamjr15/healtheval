"""Report current Python and Node advisories; findings keep a nonzero exit code."""
import subprocess
import sysconfig


def main() -> int:
    commands = [
        ["uvx", "pip-audit==2.10.1", "--path", sysconfig.get_path("purelib")],
        ["npm", "audit"],
    ]
    failed = False
    for command in commands:
        failed = subprocess.run(command).returncode != 0 or failed
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
