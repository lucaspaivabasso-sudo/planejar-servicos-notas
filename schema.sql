
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
        check (role in ('admin','funcionario')),
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

-- Função utilitária: verifica se usuário é admin
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

-- RLS
alter table public.profiles enable row level security;
alter table public.servicos enable row level security;
alter table public.notas enable row level security;

-- Perfis: cada usuário vê o próprio; admin vê todos
drop policy if exists "profiles_select" on public.profiles;
create policy "profiles_select"
on public.profiles for select
to authenticated
using (id = auth.uid() or public.is_admin());

-- Serviços: funcionário insere e vê os próprios; admin vê todos
drop policy if exists "servicos_select" on public.servicos;
create policy "servicos_select"
on public.servicos for select
to authenticated
using (usuario_id = auth.uid() or public.is_admin());

drop policy if exists "servicos_insert" on public.servicos;
create policy "servicos_insert"
on public.servicos for insert
to authenticated
with check (usuario_id = auth.uid());

drop policy if exists "servicos_update_admin" on public.servicos;
create policy "servicos_update_admin"
on public.servicos for update
to authenticated
using (public.is_admin())
with check (public.is_admin());

-- Notas: funcionário insere e vê as próprias; admin vê/atualiza todas
drop policy if exists "notas_select" on public.notas;
create policy "notas_select"
on public.notas for select
to authenticated
using (usuario_id = auth.uid() or public.is_admin());

drop policy if exists "notas_insert" on public.notas;
create policy "notas_insert"
on public.notas for insert
to authenticated
with check (usuario_id = auth.uid());

drop policy if exists "notas_update_admin" on public.notas;
create policy "notas_update_admin"
on public.notas for update
to authenticated
using (public.is_admin())
with check (public.is_admin());

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
        or public.is_admin()
    )
);

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
