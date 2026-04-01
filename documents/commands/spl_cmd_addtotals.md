---
 command: addtotals
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/addtotals
 title: addtotals
 download_date: 2026-02-03 09:01:24
---

 # addtotals

The addtotals command computes the arithmetic sum of all numeric fields for each search result. The results appear in the Statistics tab.

You can specify a list of fields that you want the sum for, instead of calculating every numeric field. The sum is placed in a new field.

If col=true, the addtotals command computes the column totals, which adds a new result at the end that represents the sum of each field. labelfield, if specified, is a field that will be added to this summary event with the value set by the 'label' option. Alternately, instead of using the  addtotals col=true command, you can use the addcoltotals command to calculate a summary event.

addtotals [row=<bool>] [col=<bool>] [labelfield=<field>] [label=<string>] [fieldname=<field>] [<field-list>]

#### Required arguments

#### Optional arguments

The addtotals command is a distributable streaming command, except when is used to calculate column totals. When used to calculate column totals, the addtotals command is a transforming command. See Command types.

#### 1: Calculate the sum of the numeric fields of each event

This example uses events that list the numeric sales for each product and quarter, for example:

| products | quarter | sales | quota |
| --- | --- | --- | --- |
| ProductA | QTR1 | 1200 | 1000 |
| ProductB | QTR1 | 1400 | 1550 |
| ProductC | QTR1 | 1650 | 1275 |
| ProductA | QTR2 | 1425 | 1300 |
| ProductB | QTR2 | 1175 | 1425 |
| ProductC | QTR2 | 1550 | 1450 |
| ProductA | QTR3 | 1300 | 1400 |
| ProductB | QTR3 | 1250 | 1125 |
| ProductC | QTR3 | 1375 | 1475 |
| ProductA | QTR4 | 1550 | 1300 |
| ProductB | QTR4 | 1700 | 1225 |
| ProductC | QTR4 | 1625 | 1350 |

Use the chart command to summarize data

In this example, there are two fields specified in the BY clause with the chart command.

- The products field is referred to as the <row-split> field.
- The quarter field is referred to as the <column-split> field.

The results appear on the Statistics tab and look something like this:

| products | QTR1 | QTR2 | QTR3 | QTR4 |
| --- | --- | --- | --- | --- |
| ProductA | 1200 | 1425 | 1300 | 1550 |
| ProductB | 1400 | 1175 | 1250 | 1700 |
| ProductC | 1650 | 1550 | 1375 | 1625 |

The results appear on the Statistics tab and look something like this:

| products | QTR1 | QTR2 | QTR3 | QTR4 | Total |
| --- | --- | --- | --- | --- | --- |
| ProductA | 1200 | 1425 | 1300 | 1550 | 5475 |
| ProductB | 1400 | 1175 | 1250 | 1700 | 5525 |
| ProductC | 1650 | 1550 | 1375 | 1625 | 6200 |

Use the stats command to calculate totals

```
stats
```

The results appear on the Statistics tab and look something like this:

| products | sum(sales) |
| --- | --- |
| ProductA | 5475 |
| ProductB | 5525 |
| ProductC | 6200 |

#### 2. Specify a name for the field that contains the sums for each event

Instead of accepting the default name added by the addtotals command, you can specify a name for the field.

#### 3. Use wildcards to specify the names of the fields to sum

Calculate the sums for the fields that begin with amount or that contain the text size in the field name. Save the sums in the field called TotalAmount.

#### 4. Calculate the sum for a specific field

In this example, the row calculations are turned off and the column calculations are turned on. The total for only a single field, sum(quota), is calculated.

- The labelfield argument specifies in which field the label for the total appears. The default label is Total.

The results appear on the Statistics tab and look something like this:

| quarter | sum(quota) |
| --- | --- |
| QTR1 | 3825 |
| QTR2 | 4175 |
| QTR3 | 4000 |
| QTR4 | 3875 |
| Total | 15875 |

#### 5. Calculate the field totals and add custom labels to the totals

Calculate the sum for each quarter and product, and calculate a grand total.

- The labelfield argument specifies in which field the label for the total appears, which in this example is products.
- The label argument is used to specify the label Quarterly Totals for the labelfield, instead of using the default label Total.
- The fieldname argument is used to specify the label Product Totals for the row totals.

The results appear on the Statistics tab and look something like this:

| products | QTR1 | QTR2 | QTR3 | QTR4 | Product Totals |
| --- | --- | --- | --- | --- | --- |
| ProductA | 1200 | 1425 | 1300 | 1550 | 5475 |
| ProductB | 1400 | 1175 | 1250 | 1700 | 5525 |
| ProductC | 1650 | 1550 | 1375 | 1625 | 6200 |
| Quarterly Totals | 4250 | 4150 | 3925 | 4875 | 17200 |
 