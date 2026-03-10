"""
planner_examples.py — WebMall planner code examples from the NeurIPS paper.

These are real LLM-generated plans (hardcoded here for offline verification).
"""

# ── Example 1: Find cheapest price ───────────────────────────────────────────

CHEAPEST_PRICE = dict(
    name="Find cheapest price (Asus ROG Ryujin II ARGB 360mm)",
    expected_stores=[
        "http://localhost:8081/",
        "http://localhost:8082/",
        "http://localhost:8083/",
        "http://localhost:8084/",
    ],
    code='''\
product = "Asus ROG Ryujin II ARGB 360mm Liquid CPU Cooler"
stores = ["http://localhost:8081/", "http://localhost:8082/", "http://localhost:8083/",
          "http://localhost:8084/"]
results = []

for store in stores:
    url_or_none = search(store, product)
    if url_or_none is not None:
        open_page(url_or_none)
        price_text = prompt(
            "On this product page, find the main current selling price of the product. "
            "Return only the numeric price as plain text using a dot as the decimal "
            "separator and no thousand separators or currency symbols (e.g., 129.99)."
        )
        if price_text:
            price_value = float(price_text.strip())
            results.append((store, url_or_none, price_value))

if len(results) > 0:
    cheapest = min(results, key=lambda x: x[2])
    final_answer = str(cheapest[2])
else:
    final_answer = "Done"

open_page("http://localhost:3000/")
fill_text_field("Solution field", final_answer)
press_button("Submit Final Result")
''',
)


# ── Example 2: Find all offers and add to cart ───────────────────────────────

ADD_ALL_TO_CART = dict(
    name="Find all offers (Antec C8 ARGB Gaming Case) and add to cart",
    expected_stores=[
        "http://localhost:8081/",
        "http://localhost:8082/",
        "http://localhost:8083/",
        "http://localhost:8084/",
    ],
    code='''\
stores = [
    ("E-Store Athletes", "http://localhost:8081/"),
    ("TechTalk",         "http://localhost:8082/"),
    ("CamelCases",       "http://localhost:8083/"),
    ("Hardware Cafe",    "http://localhost:8084/"),
]
product = "Antec C8 ARGB Gaming Case"
found_offers = []

for store_name, store_url in stores:
    url_or_none = search(store_url, product)
    if url_or_none is not None:
        open_page(url_or_none)
        title = prompt("Extract the exact product title shown on this page.")
        if "Antec C8 ARGB" in title:
            added = add_to_cart(url_or_none)
            if not added:
                open_page(url_or_none)
                prompt(
                    "Click the Add to Cart (or similar) button to add this product "
                    "to the cart. If a simple option selection is required, choose "
                    "the default/first available and complete adding to cart."
                )
            found_offers.append((store_name, url_or_none))

open_page("http://localhost:3000/")
fill_text_field("Solution field", "Done")
press_button("Submit Final Result")
''',
)


# ── Example 3: Find cheapest, checkout with credit card ──────────────────────

CHEAPEST_CHECKOUT = dict(
    name="Find cheapest offer (Asrock B550 PHANTOM GAMING 4), checkout",
    expected_stores=[
        "E-Store Athletes",
        "TechTalk",
        "CamelCases",
        "Hardware Cafe",
    ],
    code='''\
stores = ["E-Store Athletes", "TechTalk", "CamelCases", "Hardware Cafe"]
product = "Asrock B550 PHANTOM GAMING 4"
offers = []

for store in stores:
    url = search(store, product)
    if url is not None:
        open_page(url)
        price_text = prompt(
            "Extract the product price from this page in USD as a plain number "
            "(e.g., 129.99). Output only the number."
        )
        offers.append({"store": store, "url": url, "price": float(price_text)})

if len(offers) == 0:
    open_page("http://localhost:3000/")
    fill_text_field("Solution field", "Done")
    press_button("Submit Final Result")
else:
    selected = min(offers, key=lambda o: o["price"])
    selected_store = selected["store"]
    selected_url   = selected["url"]

    open_page(selected_url)
    add_to_cart(selected_url)
    checkout(selected_store)

    prompt(
        "If you are not on the checkout page, navigate to the cart "
        "and then proceed to checkout."
    )

    fill_text_field("Full Name",      "Jessica Morgan")
    fill_text_field("First Name",     "Jessica")
    fill_text_field("Last Name",      "Morgan")
    fill_text_field("Email",          "jessica.morgan@yahoo.com")
    fill_text_field("Address",        "742 Maple Avenue")
    fill_text_field("Street",         "Maple Avenue")
    fill_text_field("House number",   "742")
    fill_text_field("City",           "Chicago")
    fill_text_field("State",          "IL")
    fill_text_field("ZIP",            "60614")
    fill_text_field("Country",        "USA")

    press_button("Credit Card")
    fill_text_field("Card Number",    "4242424242424242")
    fill_text_field("Expiry",         "12/28")
    fill_text_field("CVV",            "123")

    press_button("Place Order")

    order_info = prompt(
        "Extract the order confirmation number or order ID from the confirmation "
        "page. If none is visible, return a short confirmation message. "
        "Output only the extracted text."
    )

    open_page("http://localhost:3000/")
    if order_info and len(order_info.strip()) > 0:
        fill_text_field("Solution field", order_info.strip())
    else:
        fill_text_field("Solution field", "Done")
    press_button("Submit Final Result")
''',
)


# ── Example 4 (mutant): deliberately broken — missing submit on one branch ───
# Used to demonstrate the verifier catching a real bug.

BROKEN_MISSING_SUBMIT = dict(
    name="[MUTANT] Cheapest price — submit missing on empty-results branch",
    expected_stores=[
        "http://localhost:8081/",
        "http://localhost:8082/",
        "http://localhost:8083/",
        "http://localhost:8084/",
    ],
    code='''\
product = "Asus ROG Ryujin II ARGB 360mm Liquid CPU Cooler"
stores = ["http://localhost:8081/", "http://localhost:8082/", "http://localhost:8083/",
          "http://localhost:8084/"]
results = []

for store in stores:
    url_or_none = search(store, product)
    if url_or_none is not None:
        open_page(url_or_none)
        price_text = prompt("Find the current selling price. Return only the number.")
        if price_text:
            results.append((store, url_or_none, float(price_text.strip())))

if len(results) > 0:
    cheapest = min(results, key=lambda x: x[2])
    open_page("http://localhost:3000/")
    fill_text_field("Solution field", str(cheapest[2]))
    press_button("Submit Final Result")
# BUG: no else-branch — if results is empty, nothing is submitted!
''',
)


# ── Example 5 (mutant): fill happens AFTER submit ────────────────────────────

BROKEN_FILL_AFTER_SUBMIT = dict(
    name="[MUTANT] Submit called before solution field is filled",
    expected_stores=[
        "http://localhost:8081/",
        "http://localhost:8082/",
        "http://localhost:8083/",
        "http://localhost:8084/",
    ],
    code='''\
product = "Asus ROG Ryujin II ARGB 360mm Liquid CPU Cooler"
stores = ["http://localhost:8081/", "http://localhost:8082/", "http://localhost:8083/",
          "http://localhost:8084/"]
results = []

for store in stores:
    url_or_none = search(store, product)
    if url_or_none is not None:
        open_page(url_or_none)
        price_text = prompt("Find the current selling price. Return only the number.")
        if price_text:
            results.append((store, url_or_none, float(price_text.strip())))

cheapest = min(results, key=lambda x: x[2]) if results else None
final_answer = str(cheapest[2]) if cheapest else "Done"

open_page("http://localhost:3000/")
press_button("Submit Final Result")   # BUG: submit before fill!
fill_text_field("Solution field", final_answer)
''',
)

ALL_EXAMPLES = [
    CHEAPEST_PRICE,
    ADD_ALL_TO_CART,
    CHEAPEST_CHECKOUT,
    BROKEN_MISSING_SUBMIT,
    BROKEN_FILL_AFTER_SUBMIT,
]
