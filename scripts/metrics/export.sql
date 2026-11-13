-- Только поля B3. Группы и карточки получают номера, действующие в пределах выгрузки.
SELECT COALESCE(jsonb_agg(to_jsonb(event_row) ORDER BY recorded_at, run, event_id), '[]'::jsonb)
FROM (
    SELECT dense_rank() OVER (ORDER BY owner_id, session_id, scenario_id) AS run,
           event_id, scenario, event, source, status, recorded_at,
           CASE WHEN action_id IS NOT NULL
                THEN dense_rank() OVER (PARTITION BY owner_id, session_id, scenario_id ORDER BY action_id)
           END AS action
    FROM core.product_events
) AS event_row;
