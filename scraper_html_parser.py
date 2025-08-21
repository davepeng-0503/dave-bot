#!/usr/bin/env python
"""
This module provides functions to parse HTML content from Google Maps
search results and extract structured data about restaurants.
"""
import logging
import re
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup, Tag

from code_agent_models import Restaurant

# --- Configuration for Dynamic Class Finding ---

# A URL that is known to contain a specific restaurant's details.
# This is used to dynamically determine the CSS classes used by Google Maps.
# The user can update this URL and the model below if the scraper breaks.
EXAMPLE_URL = "https://www.google.com/maps/search/Katz's+Delicatessen+New+York"

# The known details of the restaurant at the EXAMPLE_URL.
# This model is used as a ground truth to find the corresponding HTML elements.
EXAMPLE_RESTAURANT = Restaurant(
    name="Katz's Delicatessen",
    # A distinctive part of the address is usually sufficient.
    address="Houston St",
    rating=4.6,
    # A simplified version of cuisine type is fine.
    cuisine=["Deli"],
)

# A realistic User-Agent is crucial to avoid being blocked.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
}

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class ClassFinder:
    """
    Dynamically finds the CSS class names for restaurant data points
    by scraping a known example page. This makes the scraper more resilient
    to website layout changes.
    """

    def __init__(self):
        self._class_names: Optional[Dict[str, Any]] = None

    def _find_classes(self) -> Dict[str, Any]:
        """
        Fetches the example URL and inspects the HTML to find the class names
        for various data points based on the EXAMPLE_RESTAURANT model.
        """
        logging.info("Attempting to dynamically find CSS classes for scraping...")
        try:
            response = requests.get(EXAMPLE_URL, headers=HEADERS, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to fetch example URL for class finding: {e}")
            return {}

        # 1. Find the main container for a single search result.
        # We find the element with the name, then walk up its parents until we find
        # one that also contains the address. This is likely the result container.
        name_element = soup.find(string=re.compile(EXAMPLE_RESTAURANT.name))
        if not name_element:
            logging.error("Could not find the example restaurant's name in the HTML.")
            return {}

        result_container_tag = None
        for parent in name_element.find_parents("div"):
            # Check if a known part of the address is in the parent's text
            if EXAMPLE_RESTAURANT.address and EXAMPLE_RESTAURANT.address in parent.get_text():
                result_container_tag = parent
                break  # Found the closest parent containing both

        if not result_container_tag or not result_container_tag.get("class"):
            logging.error("Could not find a common container for the example restaurant.")
            return {}

        # Heuristic: The first class in the list is often the most specific one.
        result_container_class = result_container_tag.get("class")[0]

        # 2. Within the container, find the specific classes for each element.
        container_soup = result_container_tag

        name_tag = container_soup.find(string=re.compile(EXAMPLE_RESTAURANT.name)).parent
        name_class = name_tag.get("class")[0] if name_tag and name_tag.get("class") else None

        rating_regex = re.compile(f"{EXAMPLE_RESTAURANT.rating}\\s+stars")
        rating_tag = container_soup.find("span", attrs={"aria-label": rating_regex})
        rating_class = rating_tag.get("class")[0] if rating_tag and rating_tag.get("class") else None

        details_class = None
        if EXAMPLE_RESTAURANT.cuisine:
            cuisine_tag = container_soup.find(string=re.compile(EXAMPLE_RESTAURANT.cuisine[0]))
            if cuisine_tag:
                # The structure is often <div><span>Cuisine</span></div>. The class is on the div.
                details_tag = cuisine_tag.find_parent("div")
                if details_tag and details_tag.get("class"):
                    details_class = details_tag.get("class")[0]

        found_classes = {
            "result_container": result_container_class,
            "name": name_class,
            "rating": rating_class,
            "details": details_class,
        }

        logging.info(f"Dynamically found classes: {found_classes}")

        if not all(found_classes.values()):
            logging.warning("Failed to find one or more required dynamic classes. Parsing may fail.")
            return {}

        return found_classes

    def get_class_names(self) -> Dict[str, Any]:
        """
        Returns the dictionary of class names, finding them if they
        haven't been found yet (cached).
        """
        if self._class_names is None:
            self._class_names = self._find_classes()
            if not self._class_names:
                logging.error("Could not determine dynamic classes. Scraper will likely fail.")
        return self._class_names or {}


# Instantiate the class finder at the module level.
# The classes will be determined once when the module is first used.
CLASS_FINDER = ClassFinder()


def _get_text_safe(element: Optional[Tag]) -> Optional[str]:
    """Safely gets stripped text from a BeautifulSoup Tag."""
    return element.get_text(strip=True) if element else None


def parse_google_maps_restaurants(html_content: str) -> List[Restaurant]:
    """
    Parses the HTML content of a Google Maps search results page to extract restaurant data.

    This version dynamically determines the CSS classes to use by inspecting a
    known restaurant page, making it more resilient to website changes.

    Args:
        html_content: The HTML content of the page as a string.

    Returns:
        A list of Restaurant objects.
    """
    class_names = CLASS_FINDER.get_class_names()
    if not class_names:
        return []

    soup = BeautifulSoup(html_content, "lxml")
    restaurants: List[Restaurant] = []

    # The main container for search results often has a 'role' of 'feed'.
    feed_container = soup.find("div", attrs={"role": "feed"})
    if not feed_container:
        return []

    # Find all result containers using the dynamically found class.
    results = feed_container.find_all("div", class_=class_names["result_container"])

    for result in results:
        try:
            name_element = result.find(class_=class_names["name"])
            name = _get_text_safe(name_element)
            if not name:
                continue

            rating_element = result.find("span", class_=class_names["rating"])
            rating_text = rating_element.get("aria-label", "") if rating_element else ""

            rating_val: Optional[float] = None
            reviews_count_val: Optional[int] = None

            if rating_text:
                rating_match = re.search(r"([\d.]+)\s+stars", rating_text)
                if rating_match:
                    rating_val = float(rating_match.group(1))

                reviews_match = re.search(r"([\d,]+)\s+Reviews", rating_text, re.IGNORECASE)
                if reviews_match:
                    reviews_count_val = int(reviews_match.group(1).replace(",", ""))

            details_elements = result.find_all("div", class_=class_names["details"])

            address: Optional[str] = None
            cuisine_list: List[str] = []

            for detail in details_elements:
                detail_text = _get_text_safe(detail)
                if not detail_text:
                    continue

                # Simple heuristic to distinguish cuisine from address.
                if "·" not in detail_text and len(detail_text.split()) < 4:
                    cuisine_list.extend([c.strip() for c in detail_text.split("·")[0].split(",") if c.strip()])
                else:
                    cleaned_address = re.sub(r"^(Open|Closed)\s*·\s*", "", detail_text).strip()
                    if len(cleaned_address) > len(detail_text.split(" ")):
                        address = cleaned_address

            phone_number: Optional[str] = None
            website: Optional[str] = None

            restaurant = Restaurant(
                name=name,
                address=address,
                phone_number=phone_number,
                website=website,
                rating=rating_val,
                reviews_count=reviews_count_val,
                cuisine=list(set(cuisine_list)),
            )
            restaurants.append(restaurant)

        except Exception as e:
            logging.warning(f"Failed to parse a restaurant entry for '{name}', skipping. Error: {e}")
            continue

    return restaurants
