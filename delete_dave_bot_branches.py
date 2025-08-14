import subprocess
import sys

def run_command(command):
    """Runs a command and returns its output, exiting on error."""
    try:
        # Using text=True to get stdout/stderr as strings
        result = subprocess.run(
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(command)}", file=sys.stderr)
        print(f"Stderr: {e.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("Error: 'git' command not found. Is Git installed and in your PATH?", file=sys.stderr)
        sys.exit(1)

def delete_local_branches():
    """Finds and deletes local git branches prefixed with 'dave-bot'."""
    print("--- Checking local branches ---")
    try:
        local_branches_str = run_command(["git", "branch"])
    except SystemExit:
        print("Could not retrieve local branches. Is this a git repository?", file=sys.stderr)
        return

    if not local_branches_str:
        print("No local branches found.")
        return

    branches_to_delete = []
    current_branch = ""

    for line in local_branches_str.split('\n'):
        branch_name = line.strip()
        if not branch_name:
            continue
        
        is_current = False
        if branch_name.startswith("* "):
            branch_name = branch_name[2:]
            is_current = True
            current_branch = branch_name

        if branch_name.startswith("dave-bot"):
            if is_current:
                print(f"Cannot delete current branch '{branch_name}'. Please switch branches and re-run.")
            else:
                branches_to_delete.append(branch_name)

    if not branches_to_delete:
        print("No local 'dave-bot' branches to delete.")
        return

    print("\nFound local branches to delete:")
    for branch in branches_to_delete:
        print(f"- {branch}")

    for branch in branches_to_delete:
        print(f"Deleting local branch '{branch}'...")
        run_command(["git", "branch", "-D", branch])
        print(f"Successfully deleted local branch '{branch}'.")

def delete_remote_branches():
    """Finds and deletes remote git branches prefixed with 'dave-bot'."""
    print("\n--- Checking remote branches ---")
    
    # Fetch and prune to get the latest state from the 'origin' remote
    print("Fetching from origin and pruning stale branches...")
    try:
        run_command(["git", "fetch", "origin", "--prune"])
    except SystemExit:
        print("Could not fetch from 'origin'. Does the remote exist?", file=sys.stderr)
        return


    remote_branches_str = run_command(["git", "branch", "-r"])
    if not remote_branches_str:
        print("No remote-tracking branches found.")
        return

    branches_to_delete = []
    for line in remote_branches_str.split('\n'):
        branch_ref = line.strip()
        # Skip empty lines or symbolic refs like 'origin/HEAD -> origin/main'
        if not branch_ref or '->' in branch_ref:
            continue

        # Expecting 'origin/branch-name'
        # We split only on the first '/' to handle branch names with slashes
        parts = branch_ref.split('/', 1)
        if len(parts) == 2:
            remote, branch_name = parts
            if remote == "origin" and branch_name.startswith("dave-bot"):
                branches_to_delete.append(branch_name)

    if not branches_to_delete:
        print("No remote 'dave-bot' branches to delete on 'origin'.")
        return

    print("\nFound remote branches on 'origin' to delete:")
    for branch in branches_to_delete:
        print(f"- {branch}")

    for branch in branches_to_delete:
        print(f"Deleting remote branch 'origin/{branch}'...")
        run_command(["git", "push", "origin", "--delete", branch])
        print(f"Successfully deleted remote branch 'origin/{branch}'.")

def main():
    """Main function to run the branch deletion script."""
    print("Starting cleanup of 'dave-bot' branches...")
    delete_local_branches()
    delete_remote_branches()
    print("\nCleanup script finished.")

if __name__ == "__main__":
    main()
