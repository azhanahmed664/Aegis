-- State snapshot contract used by SupabaseEngine.save_state/load_states.
-- Apply once in the Supabase SQL editor. The daemon needs
-- SUPABASE_SERVICE_ROLE_KEY; Streamlit uses only the anon SUPABASE_KEY.

create table if not exists public.aegis_market_state (
    state_key text primary key,
    payload jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create table if not exists public.aegis_orderflow_state (
    state_key text primary key,
    payload jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

create table if not exists public.aegis_macro_briefing (
    state_key text primary key,
    payload jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

alter table public.aegis_market_state enable row level security;
alter table public.aegis_orderflow_state enable row level security;
alter table public.aegis_macro_briefing enable row level security;

grant select on public.aegis_market_state to anon, authenticated;
grant select on public.aegis_orderflow_state to anon, authenticated;
grant select on public.aegis_macro_briefing to anon, authenticated;
grant all on public.aegis_market_state to service_role;
grant all on public.aegis_orderflow_state to service_role;
grant all on public.aegis_macro_briefing to service_role;

drop policy if exists aegis_market_state_read on public.aegis_market_state;
create policy aegis_market_state_read on public.aegis_market_state
    for select to anon, authenticated using (true);

drop policy if exists aegis_orderflow_state_read on public.aegis_orderflow_state;
create policy aegis_orderflow_state_read on public.aegis_orderflow_state
    for select to anon, authenticated using (true);

drop policy if exists aegis_macro_briefing_read on public.aegis_macro_briefing;
create policy aegis_macro_briefing_read on public.aegis_macro_briefing
    for select to anon, authenticated using (true);
