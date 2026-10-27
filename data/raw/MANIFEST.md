# Raw source files - as published by each council

Downloaded 2026-10-25 from the councils' own websites. Nothing here is edited.
`scripts/build_sample_data.py` maps these into `data/sample/` (one schema, provenance ids).

Why these windows: each council publishes on its own cadence and lag, so there is no
single month all three have published beyond April 2026. I take the NEWEST six months
each council has released and badge every number with its council's window. That
mismatch is the fragmentation the project exists to federate.

## Woking Borough Council (monthly, by payment/clearance date)
Page: https://www.woking.gov.uk/your-council/data-finance-performance/accounts-finance/financial-spend-data

| File | Period | Source URL |
|---|---|---|
| woking_2025_11.csv | Nov 2025 | https://www.woking.gov.uk/sites/default/files/2026-01/Local%20spend%20data%20-%20November%202025.csv |
| woking_2025_12.xlsx | Dec 2025 | https://www.woking.gov.uk/sites/default/files/2026-02/Local%20spend%20data%20-%20December%202025.xlsx |
| woking_2026_01.xlsx | Jan 2026 | https://www.woking.gov.uk/sites/default/files/2026-02/Local%20spend%20data%20January%202026.xlsx |
| woking_2026_02.csv | Feb 2026 | https://www.woking.gov.uk/sites/default/files/2026-05/Local%20Spend%20Data%20-%20February%202026.csv |
| woking_2026_03.csv | Mar 2026 | https://www.woking.gov.uk/sites/default/files/2026-05/Local%20Spend%20Data%20-%20March%202026.csv |
| woking_2026_04.csv | Apr 2026 (newest published) | https://www.woking.gov.uk/sites/default/files/2026-10/Local%20spend%20data%20-%20April%202026.csv |
| woking_contracts_2026_27_q1.csv | Contracts register 2026/27 Q1 | https://www.woking.gov.uk/sites/default/files/2026-07/Woking%20Borough%20Council%20contracts%20register%202026%20to%202027%20-%20quarter%201.csv |
| woking_pipeline_2026_27_q1.csv | Pipeline register 2026/27 Q1 (not used yet) | https://www.woking.gov.uk/sites/default/files/2026-07/Woking%20Borough%20Council%20pipeline%20contracts%20register%202026%20to%202027%20-%20quarter%201.csv |
| woking_cts_scheme_2026.pdf | Council Tax Support scheme from 1 April 2026 | https://www.woking.gov.uk/sites/default/files/2025-03/Council%20Tax%20Support%20scheme.pdf |

Contracts page: https://www.woking.gov.uk/your-council/council-tenders-contracts

## Guildford Borough Council (quarterly, financial-year quarters, by payment date)
Page: https://www.guildford.gov.uk/article/25083/Annual-spending-data

| File | Period | Source URL |
|---|---|---|
| guildford_2026_Q1.xlsx | Apr-Jun 2026 | https://www.guildford.gov.uk/media/37940/Spending-data-2026-Q1/xls/Spending_data_2026_Q1.xlsx |
| guildford_2026_Q2.xlsx | Jul-Sep 2026 (newest published) | https://www.guildford.gov.uk/media/38216/Spending-data-2026-Q2/xls/Spending_data_2026_Q2_m45f7m2tl51c.xlsx |
| guildford_contracts_2026_q4.xlsx | Contracts register, data as at 1 Apr 2026 | https://www.guildford.gov.uk/media/37371/Contract-Register-2026/xls/GBC_CONTRACT_REGISTER_Q4.xlsx |
| guildford_ctr_scheme_working_age_2026.pdf | Council Tax Reduction scheme (working age) 2026 | https://www.guildford.gov.uk/media/37463/Guildford-Council-Tax-Reductions-Scheme/pdf/Guildford_CTR_Scheme_Working_Age_2026.pdf |

Note: Guildford labels quarters by financial year start ("2026 Q2" = Jul-Sep 2026).
Contracts page: https://www.guildford.gov.uk/DoingbusinesswithGBC

## Waverley Borough Council (half-yearly, by accounting period)
Page: https://www.waverley.gov.uk/access-to-information/transparency-and-open-data

| File | Period | Source URL |
|---|---|---|
| waverley_over500_q1q2_2026_27.csv | Apr-Sep 2026 (periods 1-6 of 2026/27) | https://www.waverley.gov.uk/Portals/0/Documents/services/council-information/freedom-of-information-and-data/data%20transparency/over-500-spend-q1-q2-2026-27.csv |
| waverley_contracts_fy2526_q4.xlsx | Contracts register, data as at 1 Apr 2026 | https://www.waverley.gov.uk/Portals/0/Documents/services/council-information/freedom-of-information-and-data/data%20transparency/waverley-borough-council-contract-register-fy2526-q4.xlsx |

Waverley does not publish a payment date, only the accounting period and invoice date.
Contracts page: https://www.waverley.gov.uk/services/business-and-licensing/doing-business-with-waverley/providing-your-services-to-the-council

## SHA-256 (first 16 hex) at download time
```
70e942f4d4c2182f guildford/guildford_2026_Q1.xlsx
54e4226abf5705e6 guildford/guildford_2026_Q2.xlsx
b5f6015a00e26200 guildford/guildford_contracts_2026_q4.xlsx
52cd1f1bc5d8dcd5 guildford/guildford_ctr_scheme_working_age_2026.pdf
03e8cb9aee40cfdb waverley/waverley_contracts_fy2526_q4.xlsx
3e34c81d11635bf2 waverley/waverley_over500_q1q2_2026_27.csv
0d393f9773f4fc6e woking/woking_2025_11.csv
619d0c360dabab68 woking/woking_2025_12.xlsx
e2759b9c170afc48 woking/woking_2026_01.xlsx
280f87f28f5d3445 woking/woking_2026_02.csv
c82a8947a81c483e woking/woking_2026_03.csv
5d76ce4ce62a4841 woking/woking_2026_04.csv
a7506584382f7d2b woking/woking_contracts_2026_27_q1.csv
04baa6f7dfdc381f woking/woking_cts_scheme_2026.pdf
ab7da9ee013f1c2d woking/woking_pipeline_2026_27_q1.csv
```

## Licence
Published under each council's open data terms (Open Government Licence v3 unless the
page states otherwise). Personal data handling: rows whose payee is a natural person are
dropped by the build script, and card-holder names are never copied.
