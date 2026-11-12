
                WITH semantic AS (
                    SELECT id, document_id, text, metadata,
                           row_number() OVER (ORDER BY embedding <=> CAST(:query_embedding AS vector), id) AS rank
                    FROM chunks
                    ORDER BY embedding <=> CAST(:query_embedding AS vector), id
                    LIMIT :top_k
                ),
                lexical_query AS MATERIALIZED (
                    SELECT plainto_tsquery('english', :query_text) AS terms
                    FROM (SELECT count(*) FROM semantic) AS semantic_ready
                ),
                keyword AS (
                    SELECT id, document_id, text, metadata,
                           row_number() OVER (ORDER BY ts_rank(search_vector, lexical_query.terms) DESC, id) AS rank
                    FROM chunks
                    CROSS JOIN lexical_query
                    WHERE search_vector @@ lexical_query.terms
                    ORDER BY ts_rank(search_vector, lexical_query.terms) DESC, id
                    LIMIT :top_k
                ),
                fused AS (
                    SELECT
                        COALESCE(semantic.id, keyword.id) AS id,
                        COALESCE(semantic.document_id, keyword.document_id) AS document_id,
                        COALESCE(semantic.text, keyword.text) AS text,
                        COALESCE(semantic.metadata, keyword.metadata) AS metadata,
                        COALESCE(1.0 / (:rrf_k + semantic.rank), 0.0)
                            + COALESCE(1.0 / (:rrf_k + keyword.rank), 0.0) AS score
                    FROM semantic
                    FULL OUTER JOIN keyword ON semantic.id = keyword.id
                )
                SELECT id, document_id, text, metadata, score
                FROM fused
                ORDER BY score DESC, id
                LIMIT :top_k
