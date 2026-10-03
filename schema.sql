-- Run in Supabase > SQL Editor. Existing tables (bins, fill_history, collection_status) are kept.
create table if not exists bins (
  bin_id text primary key, location text, latitude double precision,
  longitude double precision, capacity int default 100, fill_level numeric default 0);
create table if not exists fill_history (
  id bigint generated always as identity primary key,
  bin_id text references bins(bin_id), date date not null, fill_level numeric not null,
  battery_pct numeric, source text default 'csv');
create table if not exists collection_status (
  bin_id text primary key references bins(bin_id), status text default 'Pending');
-- NEW: audit trail / service history (required by the capstone brief)
create table if not exists service_history (
  id bigint generated always as identity primary key,
  bin_id text references bins(bin_id), collected_at timestamptz default now(),
  fill_level_at_collection numeric, collected_by text default 'dashboard');
-- NEW: if fill_history already exists, add the two new columns
alter table fill_history add column if not exists battery_pct numeric;
alter table fill_history add column if not exists source text default 'csv';
-- Security: turn on Row Level Security. The backend uses the service_role key, which bypasses RLS,
-- so with RLS on and no public policies the anon/publishable key can no longer read or edit your data.
alter table bins enable row level security;
alter table fill_history enable row level security;
alter table collection_status enable row level security;
alter table service_history enable row level security;

-- NEW (v3): audit trail for registry changes / collections
create table if not exists audit_log (
  id bigint generated always as identity primary key,
  created_at timestamptz default now(), action text not null, bin_id text, detail text);
alter table audit_log enable row level security;
