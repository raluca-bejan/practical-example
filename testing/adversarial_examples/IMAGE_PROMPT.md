# Image generation record

Generated with the built-in image-generation tool. The image is a visual
companion to `inputs/01_placeholders.json`, not an image-ingestion test.

Saved asset: `placeholder-invoice.png`.

## Final prompt

Use case: product-mockup
Asset type: illustrative synthetic invoice for a software QA example.
Primary request: create a clear photorealistic top-down picture of a single printed sample invoice on a neutral desk, demonstrating how mandatory placeholders can look structured while conveying missing information.
Style/medium: realistic paper, restrained professional invoice typography, sharp and very readable large text, soft daylight, no extra objects.
Composition: portrait white page fills most of the image, straight-on overhead view with tiny natural shadow. No hands or people.
Text on the page, exactly:
"SYNTHETIC TEST INVOICE"
"Invoice number: TBD"
"Issue date: 2026-09-20"
"Supplier: UNKNOWN"
"Currency: EUR"
A table with headers "Description", "Quantity", "Unit price", "Amount" and one row "TBD", "2", "100.00", "200.00".
"Subtotal: 200.00"
"Tax: 38.00"
"Total: 238.00 EUR"
"TEST DATA - NOT FOR PAYMENT"
Subtly highlight the values TBD, UNKNOWN and the TBD description with pale yellow marker. Do not add a validation stamp or imply the picture was processed by the app. Do not add customer, due date, tax ID, logo, bank account, address or other invented invoice data.
Output: one polished raster image as a visual companion; the current application only accepts text, so this image is not an executable test input.
