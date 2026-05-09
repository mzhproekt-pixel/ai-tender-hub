-- Basic roster: one row per canonical entity with primary identifier and address.
SELECT
    e.id                                                          AS entity_id,
    e.canonical_name,
    e.country,
    e.legal_form,
    e.status,
    (SELECT i.value FROM entity_identifiers i
       WHERE i.entity_id = e.id AND i.scheme = 'LEI' LIMIT 1)     AS lei,
    (SELECT i.value FROM entity_identifiers i
       WHERE i.entity_id = e.id AND i.scheme = 'CIK' LIMIT 1)     AS cik,
    (SELECT a.city FROM entity_addresses a
       WHERE a.entity_id = e.id ORDER BY a.id LIMIT 1)            AS city,
    (SELECT a.region FROM entity_addresses a
       WHERE a.entity_id = e.id ORDER BY a.id LIMIT 1)            AS region,
    (SELECT a.street FROM entity_addresses a
       WHERE a.entity_id = e.id ORDER BY a.id LIMIT 1)            AS street,
    e.updated_at
FROM entities e
ORDER BY e.country NULLS LAST, e.canonical_name;
