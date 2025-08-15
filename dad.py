#!/usr/bin/env python
import json
import urllib.request

def get_dad_joke():
    """
    Fetches a random dad joke from the icanhazdadjoke.com API.

    Returns:
        str: A dad joke, or an error message if the request fails.
    """
    url = "https://icanhazdadjoke.com/"
    headers = {
        "Accept": "application/json",
        "User-Agent": "dad.py (A friendly Python script for telling dad jokes)"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return data.get("joke", "Could not find the joke in the response.")
            else:
                return f"Error: Received status code {response.status}"
    except Exception as e:
        return f"An error occurred: {e}"

def main():
    """
    Main function to get and print a dad joke.
    """
    print("Here's a dad joke for you:")
    joke = get_dad_joke()
    print(joke)

if __name__ == "__main__":
    main()
