SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';
CREATE TYPE public.message_role AS ENUM (
'user',
'assistant',
'system'
);
ALTER TYPE public.message_role OWNER TO orq41owner;
SET default_tablespace = '';
SET default_table_access_method = heap;
CREATE TABLE public.alembic_version (
version_num character varying(32) NOT NULL
);
ALTER TABLE public.alembic_version OWNER TO orq41owner;
CREATE TABLE public.chunks (
id uuid NOT NULL,
document_id uuid NOT NULL,
tenant_id character varying(64) NOT NULL,
ordinal integer NOT NULL,
text text NOT NULL,
context text,
embedding public.vector(1536) NOT NULL,
search_vector tsvector NOT NULL,
metadata jsonb,
created_at timestamp with time zone DEFAULT now() NOT NULL
);
ALTER TABLE ONLY public.chunks FORCE ROW LEVEL SECURITY;
ALTER TABLE public.chunks OWNER TO orq41owner;
CREATE TABLE public.conversations (
id uuid NOT NULL,
created_at timestamp with time zone DEFAULT now() NOT NULL,
updated_at timestamp with time zone DEFAULT now() NOT NULL,
title character varying(255),
metadata jsonb,
tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL
);
ALTER TABLE public.conversations OWNER TO orq41owner;
CREATE TABLE public.documents (
id uuid NOT NULL,
tenant_id character varying(64) NOT NULL,
source_path character varying(1024) NOT NULL,
content_hash character varying(64) NOT NULL,
doc_type character varying(32) NOT NULL,
indexing_mode character varying(32) DEFAULT 'plain'::character varying NOT NULL,
metadata jsonb,
created_at timestamp with time zone DEFAULT now() NOT NULL
);
ALTER TABLE ONLY public.documents FORCE ROW LEVEL SECURITY;
ALTER TABLE public.documents OWNER TO orq41owner;
CREATE TABLE public.messages (
id uuid NOT NULL,
conversation_id uuid NOT NULL,
role public.message_role NOT NULL,
content text NOT NULL,
created_at timestamp with time zone DEFAULT now() NOT NULL,
tenant_id character varying(64) DEFAULT 'default'::character varying NOT NULL,
sequence bigint NOT NULL
);
ALTER TABLE public.messages OWNER TO orq41owner;
ALTER TABLE public.messages ALTER COLUMN sequence ADD GENERATED ALWAYS AS IDENTITY (
SEQUENCE NAME public.messages_sequence_seq
START WITH 1
INCREMENT BY 1
NO MINVALUE
NO MAXVALUE
CACHE 1
);
CREATE TABLE public.rag_request_metrics (
id uuid NOT NULL,
request_instance_id uuid NOT NULL,
request_id uuid,
tenant_id character varying(64) NOT NULL,
mode character varying(1),
retrieval_outcome character varying(64),
memory_outcome character varying(64),
generation_outcome character varying(64),
estimated_cost_usd double precision,
input_tokens integer,
output_tokens integer,
total_latency_ms integer,
ebm25_latency_ms integer,
rewrite_calls integer,
retrieve_calls integer,
rerank_calls integer,
evaluate_calls integer,
generate_calls integer,
fallback_used boolean,
history_truncated boolean,
ebm25_selected_count integer,
history_row_cap_reached boolean,
created_at timestamp with time zone DEFAULT now() NOT NULL
);
ALTER TABLE public.rag_request_metrics OWNER TO orq41owner;
CREATE TABLE public.usage_events (
id uuid NOT NULL,
conversation_id uuid,
message_id uuid,
provider character varying(64) NOT NULL,
model_version character varying(128) NOT NULL,
prompt_version character varying(64) NOT NULL,
request_id uuid,
input_tokens integer,
output_tokens integer,
total_tokens integer,
latency_ms integer,
status character varying(32),
error_message text,
"timestamp" timestamp with time zone DEFAULT now() NOT NULL,
feedback character varying(8),
feedback_updated_at timestamp with time zone,
CONSTRAINT ck_usage_events_feedback CHECK (((feedback IS NULL) OR ((feedback)::text = ANY (ARRAY[('up'::character varying)::text, ('down'::character varying)::text]))))
);
ALTER TABLE public.usage_events OWNER TO orq41owner;
ALTER TABLE ONLY public.alembic_version
ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);
ALTER TABLE ONLY public.chunks
ADD CONSTRAINT chunks_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.conversations
ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.documents
ADD CONSTRAINT documents_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.messages
ADD CONSTRAINT messages_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.rag_request_metrics
ADD CONSTRAINT rag_request_metrics_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.rag_request_metrics
ADD CONSTRAINT rag_request_metrics_request_instance_id_key UNIQUE (request_instance_id);
ALTER TABLE ONLY public.usage_events
ADD CONSTRAINT usage_events_pkey PRIMARY KEY (id);
CREATE INDEX ix_chunks_document_id ON public.chunks USING btree (document_id);
CREATE INDEX ix_chunks_embedding_hnsw ON public.chunks USING hnsw (embedding public.vector_cosine_ops);
CREATE INDEX ix_chunks_search_vector_gin ON public.chunks USING gin (search_vector);
CREATE INDEX ix_chunks_tenant_id ON public.chunks USING btree (tenant_id);
CREATE INDEX ix_conversations_tenant_id_created_at ON public.conversations USING btree (tenant_id, created_at);
CREATE INDEX ix_documents_tenant_id ON public.documents USING btree (tenant_id);
CREATE INDEX ix_messages_conversation_id_created_at ON public.messages USING btree (conversation_id, created_at);
CREATE INDEX ix_messages_conversation_id_sequence ON public.messages USING btree (conversation_id, sequence);
CREATE INDEX ix_rag_request_metrics_created_at ON public.rag_request_metrics USING btree (created_at);
CREATE INDEX ix_rag_request_metrics_request_id ON public.rag_request_metrics USING btree (request_id);
CREATE INDEX ix_usage_events_conversation_ts ON public.usage_events USING btree (conversation_id, "timestamp");
CREATE INDEX ix_usage_events_message_id ON public.usage_events USING btree (message_id);
CREATE INDEX ix_usage_events_request_id ON public.usage_events USING btree (request_id);
CREATE UNIQUE INDEX ux_chunks_document_ordinal ON public.chunks USING btree (document_id, ordinal);
CREATE UNIQUE INDEX ux_documents_tenant_source_hash ON public.documents USING btree (tenant_id, source_path, content_hash, indexing_mode);
ALTER TABLE ONLY public.chunks
ADD CONSTRAINT chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.messages
ADD CONSTRAINT messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.usage_events
ADD CONSTRAINT usage_events_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) ON DELETE SET NULL;
ALTER TABLE ONLY public.usage_events
ADD CONSTRAINT usage_events_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id) ON DELETE SET NULL;
ALTER TABLE public.chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY chunks_tenant_isolation ON public.chunks USING (((tenant_id)::text = current_setting('app.tenant_id'::text, true))) WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)));
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY documents_tenant_isolation ON public.documents USING (((tenant_id)::text = current_setting('app.tenant_id'::text, true))) WITH CHECK (((tenant_id)::text = current_setting('app.tenant_id'::text, true)));
GRANT USAGE ON SCHEMA public TO chat_ops;
GRANT USAGE ON SCHEMA public TO chat_ops_retention;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.chunks TO rag_app;
GRANT SELECT ON TABLE public.conversations TO chat_ops;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.documents TO rag_app;
GRANT SELECT ON TABLE public.messages TO chat_ops;
GRANT INSERT ON TABLE public.rag_request_metrics TO chat_ops;
GRANT SELECT,DELETE ON TABLE public.rag_request_metrics TO chat_ops_retention;