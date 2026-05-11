"""Reusable Streamlit UI components for the workbench pages.

Components in this package never read evidence files directly — they take
already-loaded dicts from the page and render them.  That keeps cache
locality on the page (one ``data_loaders.load_*`` call) and keeps the
components testable without a live Streamlit context.
"""
