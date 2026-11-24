-- One row per list-price period of a product: order lines sold in it and the demand exposure of its category.
-- Exposure = sum over the period's days of (category order lines that day / popularity of the category's products
-- on sale that day). New products dilute the share of old ones, so exposure falls when the catalogue grows.
WITH lines AS (
    SELECT o.product_id, o.order_date, p.category
    FROM orders o
    JOIN products p USING (product_id)
    WHERE NOT o.is_fraud
),
category_day AS (
    SELECT category, order_date AS day, count(*) AS lines
    FROM lines
    GROUP BY ALL
),
pool AS (
    SELECT cd.category, cd.day, sum(p.product_popularity) AS popularity
    FROM category_day cd
    JOIN products p
      ON p.category = cd.category
     AND p.launch_date <= cd.day
     AND (p.discontinued_date IS NULL OR p.discontinued_date >= cd.day)
    GROUP BY ALL
),
daily_exposure AS (
    SELECT cd.category, cd.day, cd.lines / pool.popularity AS exposure
    FROM category_day cd
    JOIN pool USING (category, day)
),
periods AS (
    SELECT ph.product_id, p.category, ph.valid_from,
           least(coalesce(ph.valid_to, $end_date), $end_date) AS valid_to,
           ph.sales_price_gross AS price_gross
    FROM price_history ph
    JOIN products p USING (product_id)
    WHERE ph.valid_from <= $end_date
),
period_lines AS (
    SELECT pe.product_id, pe.valid_from, count(l.product_id) AS lines
    FROM periods pe
    LEFT JOIN lines l
      ON l.product_id = pe.product_id
     AND l.order_date BETWEEN pe.valid_from AND pe.valid_to
    GROUP BY ALL
),
period_exposure AS (
    SELECT pe.product_id, pe.valid_from, sum(de.exposure) AS exposure
    FROM periods pe
    JOIN daily_exposure de
      ON de.category = pe.category
     AND de.day BETWEEN pe.valid_from AND pe.valid_to
    GROUP BY ALL
)
SELECT pe.product_id, pe.category, pe.valid_from, pe.valid_to, pe.price_gross, pl.lines, px.exposure
FROM periods pe
JOIN period_lines pl USING (product_id, valid_from)
JOIN period_exposure px USING (product_id, valid_from)
ORDER BY pe.product_id, pe.valid_from
