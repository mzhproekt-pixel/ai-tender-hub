-- Entities augmented with first available email / phone / website.
SELECT
    e.id   AS entity_id,
    e.canonical_name,
    e.country,
    (SELECT c.value FROM entity_contacts c
       WHERE c.entity_id = e.id AND c.kind = 'email'   ORDER BY c.id LIMIT 1) AS email,
    (SELECT c.value FROM entity_contacts c
       WHERE c.entity_id = e.id AND c.kind = 'phone'   ORDER BY c.id LIMIT 1) AS phone,
    (SELECT c.value FROM entity_contacts c
       WHERE c.entity_id = e.id AND c.kind = 'website' ORDER BY c.id LIMIT 1) AS website
FROM entities e
WHERE EXISTS (SELECT 1 FROM entity_contacts c WHERE c.entity_id = e.id)
ORDER BY e.country NULLS LAST, e.canonical_name;
