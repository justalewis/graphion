# CrossRef deposit

DOIs for articles are registered with CrossRef. The tool generates deposit XML; you upload it to the CrossRef admin (no API submission yet).

## Per-journal setup (one-time)

In **Journal Settings** → **CrossRef** section:

- **DOI prefix** — issued by CrossRef when your organization registered (e.g., `10.21623`).
- **Member ID** — CrossRef member identifier.
- **Depositor name** — usually the journal's name.
- **Depositor email** — a real address registered with your CrossRef account. **CrossRef will reject deposits with placeholder emails.**

A **sample DOI** is computed live so you can verify the numbering pattern before depositing. Default LiCS pattern: `{prefix}/{member_id}.{volume}.{issue}.{position}` → e.g. `10.21623/1.13.1.1` for issue 13.1's first article.

The CrossRef tab at `/crossref` shows each journal's readiness — green "ready" badge when prefix, member ID, depositor name, and depositor email are all set.

## Per-article setup

Each article gets a DOI on first deposit. The DOI is computed from the journal's pattern + the article's `order_in_issue` (after issue assembly).

To override a DOI for a specific article (e.g., if you've already deposited a DOI under a different scheme), set it in the article's metadata form. The override sticks and is used in both CrossRef and JATS XML.

## Producing the XML

Two endpoints:

- `/articles/<id>/crossref.xml` — single article. Useful for one-off deposits.
- `/issues/<id>/crossref.xml` — full issue batch. Recommended for a finished issue.

Both download as `.xml` files. The CrossRef tab links to the per-issue XML from each journal's issue list.

## What the XML contains

```
<doi_batch>
  <head>
    <doi_batch_id>...</doi_batch_id>
    <timestamp>...</timestamp>
    <depositor>
      <depositor_name>Literacy in Composition Studies</depositor_name>
      <email_address>licsjournal@gmail.com</email_address>
    </depositor>
    <registrant>Literacy in Composition Studies</registrant>
  </head>
  <body>
    <journal>
      <journal_metadata>
        <full_title>Literacy in Composition Studies</full_title>
        <issn media_type="electronic">2326-5620</issn>
      </journal_metadata>
      <journal_issue>
        <publication_date><year>2026</year></publication_date>
        <journal_volume><volume>13</volume></journal_volume>
        <issue>1</issue>
      </journal_issue>
      <journal_article publication_type="full_text">
        <titles><title>...</title></titles>
        <contributors>
          <person_name sequence="first" contributor_role="author">
            <given_name>Maggie</given_name>
            <surname>Fernandes</surname>
            <affiliations><institution>
              <institution_name>University of Arkansas</institution_name>
            </institution></affiliations>
          </person_name>
          ...
        </contributors>
        <abstract>...</abstract>
        <publication_date><year>2026</year></publication_date>
        <pages>
          <first_page>1</first_page>
          <last_page>31</last_page>
        </pages>
        <doi_data>
          <doi>10.21623/1.13.1.1</doi>
          <resource>http://yourserver/articles/1/html</resource>
        </doi_data>
        <citation_list>
          <!-- Structured citations from references.bib -->
          <citation key="crawford2021">
            <journal_title>Yale University Press</journal_title>
            <author>Crawford</author>
            <cYear>2021</cYear>
            <article_title>Atlas of AI...</article_title>
          </citation>
          ...
        </citation_list>
      </journal_article>
      <!-- More articles for issue-batch XML -->
    </journal>
  </body>
</doi_batch>
```

## Manual deposit workflow

1. Verify CrossRef config in **Journal Settings** is complete (green "ready" badge on the CrossRef tab).
2. Make sure the issue is assembled (articles have `start_page` / `end_page` set).
3. Run lint on each article. Fix anything that blocks a credible deposit (missing fields, malformed ORCID, etc.).
4. From the CrossRef tab, click **Download issue XML** for the issue.
5. Sign in to <https://doi.crossref.org/> with your CrossRef admin credentials.
6. Submit the XML via the **Submission** tab (or **Submit XML** depending on UI version).
7. Wait for the success email from CrossRef. DOIs are minted at that point.

## Verifying after deposit

For each article, the DOI you deposited should resolve at `https://doi.org/<doi>` within a few hours. The resolution target is the `<resource>` URL you provided in the XML (currently the article's HTML galley on the server's host).

If your articles live on OJS, point `<resource>` at the OJS-hosted galley by setting a journal-level `resource_url_template` config (not yet exposed in the UI; needs a code edit until then).

## Common rejection reasons

- **Email mismatch** — depositor email must match the email registered with the CrossRef account.
- **Existing DOI for this article** — CrossRef detects re-deposits. Use the **Update** action in CrossRef admin rather than a fresh submit.
- **Missing required fields** — for `journal_article`, that's at least title, authors, publication date, DOI, resource URL.
- **Schema validation failures** — the XML should validate against the CrossRef XSD. The tool's output does; if something fails, file an issue.

## What's deferred to a future version

- **API-based submission** — the tool currently emits XML for manual upload. API submission (POST to `https://doi.crossref.org/servlet/deposit`) is on the roadmap; the XML doesn't change, just the upload mechanism.
- **Deposit history tracking** — knowing which DOIs have been registered vs. just generated. Useful for audit and for avoiding accidental re-deposit.
- **DOI conflict detection** — checking that two articles haven't been assigned the same DOI by accident.
