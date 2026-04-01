---
 command: analyzefields
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/analyzefields
 title: analyzefields
 download_date: 2026-02-03 09:01:31
---

 # analyzefields

Using <field> as a discrete random variable, this command analyzes all numerical fields to determine the ability for each of those fields to predict the value of the classfield. It determines the stability of the relationship between values in the target classfield and numeric values in other fields.

As a reporting command, analyzefields consumes all input results and generates one row for each numeric field in the output results. The values in that row indicate the performance of the  analyzefields command at predicting the value of a classfield. For each event, if the conditional distribution of the numeric field with the highest z-probability based on matches the actual class, the event is counted as accurate. The highest z-probablility is based on the classfield.

analyzefields classfield=<field>

You can use the abbreviation af for the analyzefields command.

The analyzefields command returns a table with five columns.

| Field | Description |
| --- | --- |
| field | The name of a numeric field from the input search results. |
| count | The number of occurrences of the field in the search results. |
| cocur | The co-occurrence of the field.  In the results where classfield is present, this is the ratio of results in which field is also present.  The cocur is 1 if the field exists in every event that has a classfield. |
| acc | The accuracy in predicting the value of the classfield, using the value of the field. This the ratio of the number of accurate predictions to the total number of events with that field.  This argument is valid only for numerical fields. |
| balacc | The balanced accuracy is the non-weighted average of the accuracies in predicted each value of the classfield. This is only valid for numerical fields. |

#### Required arguments

#### Example 1:

Analyze the numerical fields to predict the value of "is_activated".

anomalousvalue
 