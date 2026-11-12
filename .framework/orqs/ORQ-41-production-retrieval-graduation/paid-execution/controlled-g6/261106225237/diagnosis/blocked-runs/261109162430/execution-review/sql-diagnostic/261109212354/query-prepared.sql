
                WITH semantic AS (
                    SELECT id, document_id, text, metadata,
                           row_number() OVER (ORDER BY embedding <=> CAST($1 AS vector), id) AS rank
                    FROM chunks
                    ORDER BY embedding <=> CAST($1 AS vector), id
                    LIMIT $3
                ),
                keyword AS (
                    SELECT id, document_id, text, metadata,
                           row_number() OVER (ORDER BY ts_rank(search_vector, plainto_tsquery('english', $2)) DESC, id) AS rank
                    FROM chunks
                    WHERE search_vector @@ plainto_tsquery('english', $2)
                    ORDER BY ts_rank(search_vector, plainto_tsquery('english', $2)) DESC, id
                    LIMIT $3
                ),
                fused AS (
                    SELECT
                        COALESCE(semantic.id, keyword.id) AS id,
                        COALESCE(semantic.document_id, keyword.document_id) AS document_id,
                        COALESCE(semantic.text, keyword.text) AS text,
                        COALESCE(semantic.metadata, keyword.metadata) AS metadata,
                        COALESCE(1.0 / ($4 + semantic.rank), 0.0)
                            + COALESCE(1.0 / ($4 + keyword.rank), 0.0) AS score
                    FROM semantic
                    FULL OUTER JOIN keyword ON semantic.id = keyword.id
                )
                SELECT id, document_id, text, metadata, score
                FROM fused
                ORDER BY score DESC, id
                LIMIT $3
                