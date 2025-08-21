#!/usr/bin/env python
"""
This module provides functions to parse HTML content from Google Maps
search results and extract structured data about restaurants.
"""
import re
from typing import List, Optional

from bs4 import BeautifulSoup, Tag

from code_agent_models import Restaurant


def _get_text_safe(element: Optional[Tag]) -> Optional[str]:
    """Safely gets stripped text from a BeautifulSoup Tag."""
    return element.get_text(strip=True) if element else None


def parse_google_maps_restaurants(html_content: str) -> List[Restaurant]:
    """
    Parses the HTML content of a Google Maps search results page to extract restaurant data.

    Note: The selectors used here are based on observed Google Maps HTML structure
    and are subject to change. They may need to be updated if Google alters its website layout.

    Args:
        html_content: The HTML content of the page as a string.

    Returns:
        A list of Restaurant objects.
    """
    soup = BeautifulSoup(html_content, "lxml")
    restaurants: List[Restaurant] = []

    # The main container for search results often has a 'role' of 'feed'.
    # Individual results are then within this container.
    feed_container = soup.find("div", attrs={"role": "feed"})
    if not feed_container:
        return []

    # Find all result containers. 'Nv2PK' is a common class for the div containing result info.
    results = feed_container.find_all("div", class_="Nv2PK")

    for result in results:
        try:
            # Name is often in a specific class, e.g., 'DUwDvf' inside an 'a' tag
            name_element = result.find(class_="DUwDvf")
            name = _get_text_safe(name_element)
            if not name:
                continue  # Skip if there's no name

            # Rating and reviews are often in a span with an aria-label
            rating_element = result.find("span", class_="ZkP5Je")
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

            # Details like cuisine, address, etc., are often in sibling divs with class 'W4Efsd'
            details_elements = result.select("div.W4Efsd")

            address: Optional[str] = None
            cuisine_list: List[str] = []

            # A common pattern is "Cuisine · Address" or similar structures.
            # We iterate through the detail snippets to find what we need.
            for detail in details_elements:
                detail_text = _get_text_safe(detail)
                if not detail_text:
                    continue

                # Simple heuristic: if it contains common cuisine keywords or is short, it might be cuisine.
                # This is not perfect. A more robust solution might check for price symbols ($$).
                if "·" not in detail_text and len(detail_text.split()) < 4:
                    cuisine_list.extend([c.strip() for c in detail_text.split("·")[0].split(",") if c.strip()])
                # Simple heuristic: if it's longer and doesn't look like a cuisine, assume it's an address.
                else:
                    # Address might be prefixed with "Open ⋅ " or "Closed ⋅ ", remove it
                    cleaned_address = re.sub(r"^(Open|Closed)\s*·\s*", "", detail_text).strip()
                    if len(cleaned_address) > len(detail_text.split()[0]): # Check if it's more than one word
                        address = cleaned_address


            # Phone number and website are not consistently available in the list view
            # and are better scraped from the individual place's page.
            # We will leave them as None for this parser.
            phone_number: Optional[str] = None
            website: Optional[str] = None

            restaurant = Restaurant(
                name=name,
                address=address,
                phone_number=phone_number,
                website=website,
                rating=rating_val,
                reviews_count=reviews_count_val,
                cuisine=list(set(cuisine_list)),  # Remove duplicates
            )
            restaurants.append(restaurant)

        except Exception:
            # If parsing a single result fails, we skip it and continue with the next one.
            continue

    return restaurants
