# Setup

## 1. Launch it

Upload and launch the plugin as any other. It asks for the `dgm` role and
storage for its raw responses, and no key.

## 2. License its datasets

On the dashboard's **Data sources** page, each of the plugin's two datasets
is listed with the terms Coinbase's standard terms impose:

- `<instance>:daily`: kept, shown inside your organisation.
- `<instance>:live`: kept two days, shown inside your organisation.

Confirm or change each licence there, with a note saying why. What you enter
is what your deployment records; it is not a statement that your use meets
Coinbase's terms (see [Terms](terms.md)).

## 3. Entitle the plugins that read it

On the same page, entitle each reading plugin (a reporting or portfolio
plugin, say) to the datasets it should read. Nothing reads a dataset it is not
entitled to.

## 4. Set the order of sources

Where another plugin also records closes, set which dataset a reader gets
first on the **Data sources** page's priority.

## Agents

An agent you delegate to can read the plugin's two pages through its tools
(`read_connection`, `read_datasets`); the Data sources page has tools of its
own for licences, entitlements and priority.

## Synthetic mode

On a development deployment, the plugin's **Synthetic mode** setting makes it
answer from built-in synthetic responses instead of calling Coinbase, to try
it without reaching Coinbase.
