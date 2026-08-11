
# Planejar Serviços e Notas V1

Sistema multiusuário online para:

- Funcionários lançarem serviços.
- Funcionários anexarem foto/PDF de notas.
- Administrador acompanhar todos os lançamentos.
- Conferir ou rejeitar notas.
- Filtrar e visualizar despesas.
- Manter os dados em banco online (Supabase).

## 1. Criar o banco no Supabase

1. Acesse o Supabase e crie um projeto gratuito.
2. Abra `SQL Editor`.
3. Cole o conteúdo de `schema.sql` e execute.
4. Vá em `Storage` e crie um bucket chamado `notas`.
5. Deixe o bucket como **privado**.

## 2. Criar usuários

No Supabase:

`Authentication -> Users -> Add user`

Crie um usuário para você e um para cada funcionário.

Depois copie o UUID de cada usuário e cadastre na tabela `profiles`.

Exemplo:

```sql
insert into public.profiles (id, nome, role)
values ('UUID-AQUI', 'Lucas', 'admin');
```

Funcionário:

```sql
insert into public.profiles (id, nome, role)
values ('UUID-AQUI', 'João', 'funcionario');
```

## 3. Configurar as chaves

Copie:

- Project URL
- Publishable key (`sb_publishable_...`). O nome `SUPABASE_ANON_KEY` foi mantido no arquivo apenas por compatibilidade com o código.

Crie um arquivo:

`.streamlit/secrets.toml`

Baseie-se no arquivo `secrets.toml.example`.

## 4. Rodar no computador

No terminal:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 5. Colocar online

A opção mais simples para a V1 é publicar no Streamlit Community Cloud.

Suba esta pasta para um repositório GitHub privado ou público e, no Streamlit Cloud,
adicione os mesmos valores de `SUPABASE_URL` e `SUPABASE_ANON_KEY` em Secrets.

Assim cada funcionário acessará o mesmo link pelo celular.

## Segurança

- Funcionário vê apenas os próprios lançamentos.
- Administrador vê todos.
- Funcionário não pode marcar nota como conferida.
- Comprovantes ficam em bucket privado.
- Não coloque a `service_role key` dentro do aplicativo.
