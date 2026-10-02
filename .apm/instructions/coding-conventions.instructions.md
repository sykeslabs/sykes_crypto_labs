---

description: Coding and testing conventions for sykes_crypto_labs
applyTo: "**"
-------------

# Code Conventions

* Configuration is accessed only via `get_settings()`.
* Optional settings default to `None` and gate their feature.
* Use Pydantic models for every external or LLM payload.
* Validate external data; do not trust it.
* Tests mock HTTP and Supabase using `pytest-mock`.
* Tests must not access the network.
* Comments explain why, particularly when documenting real incidents or dates, and should match the existing project style.
