--
-- PostgreSQL database dump
--

\restrict dyknsAJf85rtzxQ7kueaVQa0a2xoAy9oXVRcRVsVGaEGLpegvEdeCuPbHhYdcH8

-- Dumped from database version 15.19 (Debian 15.19-1.pgdg13+2)
-- Dumped by pg_dump version 15.19 (Debian 15.19-1.pgdg13+2)

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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: activities; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.activities (
    id character varying(20) NOT NULL,
    name character varying(255) NOT NULL,
    type character varying(100) NOT NULL,
    lat double precision NOT NULL,
    lon double precision NOT NULL,
    city character varying(100),
    origin_block character varying(50),
    categories character varying(255),
    duration_estimated_min integer NOT NULL,
    duration_estimated_max integer NOT NULL,
    source_duration character varying(100),
    observation_annotation text,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT activities_check CHECK ((duration_estimated_min <= duration_estimated_max)),
    CONSTRAINT activities_duration_estimated_min_check CHECK ((duration_estimated_min > 0)),
    CONSTRAINT activities_lat_check CHECK (((lat >= ('-90'::integer)::double precision) AND (lat <= (90)::double precision))),
    CONSTRAINT activities_lon_check CHECK (((lon >= ('-180'::integer)::double precision) AND (lon <= (180)::double precision)))
);


ALTER TABLE public.activities OWNER TO postgres;

--
-- Data for Name: activities; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.activities (id, name, type, lat, lon, city, origin_block, categories, duration_estimated_min, duration_estimated_max, source_duration, observation_annotation, created_at) FROM stdin;
atividade_0002	Updated Activity No Categories	test=type	-5.8	-35.2	Natal	test	{gastronomia}	60	90	\N	\N	2026-11-08 17:00:55.828672
atividade_0003	Cultural Tour	tourism=museum	-5.8	-35.2	Natal	cultural	{cultura_historia,religioso,lazer}	120	180	\N	\N	2026-11-08 17:01:12.519852
\.


--
-- Name: activities activities_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_pkey PRIMARY KEY (id);


--
-- PostgreSQL database dump complete
--

\unrestrict dyknsAJf85rtzxQ7kueaVQa0a2xoAy9oXVRcRVsVGaEGLpegvEdeCuPbHhYdcH8

