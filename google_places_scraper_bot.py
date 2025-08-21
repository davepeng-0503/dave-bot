#!/usr/bin/env python
"""
This script provides a command-line interface to scrape restaurant information
from Google Maps based on a search query and save it to a CSV file.

It leverages a dynamic parsing approach where CSS classes for scraping are
determined at runtime by analyzing a known example restaurant page. This makes
the scraper more resilient to website updates.
"""

import argparse
import csv
import logging
import os
from typing import List

import requests

from code_agent_models import Restaurant
# Import both the parser function and the class finder instance for testing.
from scraper_html_parser import CLASS_FINDER, parse_google_maps_restaurants

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# A realistic User-Agent is crucial to avoid being blocked.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
}


def fetch_google_maps_html(query: str) -> str | None:
    """
    Fetches the HTML content for a Google Maps search query.

    Args:
        query: The search query (e.g., "restaurants in New York").

    Returns:
        The HTML content as a string, or None if the request fails.
    """
    search_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
    logging.info(f"Fetching data from URL: {search_url}")
    try:
        response = requests.get(search_url, headers=HEADERS, timeout=15)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        logging.info("Successfully fetched HTML content.")
        return response.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to fetch HTML content: {e}")
        return None


def save_restaurants_to_csv(restaurants: List[Restaurant], output_file: str) -> None:
    """
    Appends a list of restaurant data to a CSV file.

    Creates the file and writes headers if it doesn't exist.

    Args:
        restaurants: A list of Restaurant objects.
        output_file: The path to the CSV file.
    """
    if not restaurants:
        logging.info("No new restaurants to save.")
        return

    # Check if the file exists to determine if we need to write headers
    file_exists = os.path.isfile(output_file)

    try:
        with open(output_file, "a", newline="", encoding="utf-8") as f:
            # Get fieldnames from the Pydantic model
            fieldnames = list(Restaurant.model_fields.keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            for restaurant in restaurants:
                # Convert Pydantic model to a dictionary for the CSV writer
                writer.writerow(restaurant.model_dump())

        logging.info(f"Successfully saved {len(restaurants)} restaurants to {output_file}")
    except IOError as e:
        logging.error(f"Error writing to CSV file {output_file}: {e}")


def test_class_finder():
    """
    Runs the dynamic class finder and prints the results for debugging.

    This helps verify if the scraper can find the necessary CSS classes from
    the example URL. If this fails, the main scraper will not work.
    """
    logging.info("--- Running Dynamic Class Finder Test ---")
    class_names = CLASS_FINDER.get_class_names()
    if class_names and all(class_names.values()):
        logging.info("Successfully found all required dynamic class names:")
        for key, value in class_names.items():
            print(f"  - {key}: '{value}'")
        logging.info("The scraper should be able to proceed.")
    else:
        logging.error("Failed to find one or more required class names.")
        logging.error("Please check the EXAMPLE_URL and EXAMPLE_RESTAURANT in scraper_html_parser.py")
        logging.error("The scraper will likely fail to parse data.")
    logging.info("--- End of Test ---")


def main():
    """
    Main function to run the scraper bot.
    """
    parser = argparse.ArgumentParser(
        description="Google Places Scraper Bot for Restaurants. Scrapes restaurant data from Google Maps.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--query",
        type=str,
        help="The search query, e.g., 'restaurants in San Francisco'."
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default="restaurants.csv",
        help="The path to the output CSV file (default: restaurants.csv)."
    )
    parser.add_argument(
        "--test-class-finder",
        action="store_true",
        help=(
            "Run only the dynamic class finder for the example URL.\n"
            "This is useful for debugging if the scraper stops working.\n"
            "It will print the CSS classes it finds based on the hardcoded example."
        )
    )
    args = parser.parse_args()

    if args.test_class_finder:
        test_class_finder()
        return

    if not args.query:
        parser.error("--query is required for scraping. Use --help for more options.")

    logging.info(f"Starting scraper for query: '{args.query}'")

    html_content = fetch_google_maps_html(args.query)

    if html_content:
        restaurants = parse_google_maps_restaurants(html_content)
        if restaurants:
            logging.info(f"Found {len(restaurants)} restaurants.")
            save_restaurants_to_csv(restaurants, args.output_file)
        else:
            logging.warning("Could not parse any restaurant data from the HTML. The website structure might have changed.")
            logging.warning("Try running with --test-class-finder to see if the dynamic class discovery is working.")
    else:
        logging.error("Could not retrieve HTML content. Aborting.")


if __name__ == "__main__":
    main()
