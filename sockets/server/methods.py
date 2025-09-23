import subprocess

def list_updates():
    try:
        subprocess.run(
            ["pacman", "-Sy"],
            capture_output=True,
            text=True,
            check=True
        )
        result = subprocess.run(
            ["pacman", "-Sup"],
            capture_output=True,
            text=True,
            check=True
        )
        return {
            "success": True,
            "updates": result.stdout
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "exit_code": e.returncode,
            "error": e.stderr
        }

METHODS = {
    "list_updates": list_updates,
}
