
-- ============================================================
-- PLANEJAR SERVIÇOS E NOTAS - SUPABASE
-- Execute este arquivo no SQL Editor do Supabase
-- ============================================================

create extension if not exists pgcrypto;

-- Perfis dos usuários
create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    nome text not null,
    role text not null default 'funcionario'
        check (role in ('admin','gerente','funcionario')),
    ativo boolean not null default true,
    created_at timestamptz not null default now()
);

-- Serviços
create table if not exists public.servicos (
    id uuid primary key default gen_random_uuid(),
    usuario_id uuid not null references auth.users(id),
    data_servico date not null,
    cliente text not null,
    fazenda text,
    tipo_servico text not null,
    area_ha numeric(12,2) not null default 0,
    valor numeric(14,2) not null default 0,
    status text not null default 'Executado',
    observacao text,
    created_at timestamptz not null default now()
);

-- Notas
create table if not exists public.notas (
    id uuid primary key default gen_random_uuid(),
    usuario_id uuid not null references auth.users(id),
    data_nota date not null,
    fornecedor text not null,
    valor numeric(14,2) not null,
    categoria text,
    cliente text,
    fazenda text,
    forma_pagamento text,
    observacao text,
    arquivo_path text,
    arquivo_nome_original text,
    status text not null default 'Pendente'
        check (status in ('Pendente','Conferida','Rejeitada')),
    conferido_por uuid references auth.users(id),
    conferido_em timestamptz,
    created_at timestamptz not null default now()
);

-- Funções utilitárias: verifica se usuário faz parte da gestão
create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid()
      and role = 'admin'
      and ativo = true
  );
$$;


create or replace function public.is_gestao()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid()
      and role in ('admin','gerente')
      and ativo = true
  );
$$;

-- RLS
alter table public.profiles enable row level security;
alter table public.servicos enable row level security;
alter table public.notas enable row level security;

-- Perfis: cada usuário vê o próprio; admin vê todos
drop policy if exists "profiles_select" on public.profiles;
create policy "profiles_select"
on public.profiles for select
to authenticated
using (id = auth.uid() or public.is_gestao());

-- Serviços: funcionário insere e vê os próprios; admin vê todos
drop policy if exists "servicos_select" on public.servicos;
create policy "servicos_select"
on public.servicos for select
to authenticated
using (usuario_id = auth.uid() or public.is_gestao());

drop policy if exists "servicos_insert" on public.servicos;
create policy "servicos_insert"
on public.servicos for insert
to authenticated
with check (usuario_id = auth.uid());

drop policy if exists "servicos_update_admin" on public.servicos;
create policy "servicos_update_admin"
on public.servicos for update
to authenticated
using (public.is_gestao())
with check (public.is_gestao());

drop policy if exists "servicos_delete_gestao" on public.servicos;
create policy "servicos_delete_gestao"
on public.servicos for delete
to authenticated
using (public.is_gestao());

-- Notas: funcionário insere e vê as próprias; admin vê/atualiza todas
drop policy if exists "notas_select" on public.notas;
create policy "notas_select"
on public.notas for select
to authenticated
using (usuario_id = auth.uid() or public.is_gestao());

drop policy if exists "notas_insert" on public.notas;
create policy "notas_insert"
on public.notas for insert
to authenticated
with check (usuario_id = auth.uid());

drop policy if exists "notas_update_admin" on public.notas;
create policy "notas_update_admin"
on public.notas for update
to authenticated
using (public.is_gestao())
with check (public.is_gestao());

drop policy if exists "notas_delete_gestao" on public.notas;
create policy "notas_delete_gestao"
on public.notas for delete
to authenticated
using (public.is_gestao());

-- Storage: crie manualmente um bucket PRIVADO chamado "notas"
-- Depois rode as políticas abaixo.

drop policy if exists "storage_notas_insert_own" on storage.objects;
create policy "storage_notas_insert_own"
on storage.objects for insert
to authenticated
with check (
    bucket_id = 'notas'
    and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists "storage_notas_select" on storage.objects;
create policy "storage_notas_select"
on storage.objects for select
to authenticated
using (
    bucket_id = 'notas'
    and (
        (storage.foldername(name))[1] = auth.uid()::text
        or public.is_gestao()
    )
);

drop policy if exists "storage_notas_delete_gestao" on storage.objects;
create policy "storage_notas_delete_gestao"
on storage.objects for delete
to authenticated
using (bucket_id = 'notas' and public.is_gestao());

-- ============================================================
-- IMPORTANTE
-- 1) Em Authentication -> Users, crie os usuários.
-- 2) Copie o UUID de cada usuário e insira na tabela profiles.
--
-- Exemplo:
-- insert into public.profiles (id, nome, role)
-- values ('UUID-DO-USUARIO', 'Lucas', 'admin');
--
-- insert into public.profiles (id, nome, role)
-- values ('UUID-DO-FUNCIONARIO', 'João', 'funcionario');
-- ============================================================


-- ============================================================
-- ATUALIZAÇÃO V2 PARA QUEM JÁ EXECUTOU A V1
-- Execute também este bloco no projeto existente.
-- ============================================================
do $$
declare c record;
begin
  for c in
    select conname
    from pg_constraint
    where conrelid = 'public.profiles'::regclass and contype = 'c'
      and pg_get_constraintdef(oid) ilike '%role%'
  loop
    execute format('alter table public.profiles drop constraint %I', c.conname);
  end loop;
end $$;

alter table public.profiles
add constraint profiles_role_check check (role in ('admin','gerente','funcionario'));

-- As políticas acima podem ser executadas novamente com segurança porque usam DROP POLICY IF EXISTS.
