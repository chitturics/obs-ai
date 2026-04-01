---
 command: rangemap
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/rangemap
 title: rangemap
 download_date: 2026-02-03 09:14:11
---

 # rangemap

Use the rangemap command to categorize the values in a numeric field. The command adds in a new field called range to each event and displays the category in the range field. The values in the range field are based on the numeric ranges that you specify.

Set the range field to the names of any attribute_name that the value of the input field is within. If no range is matched, the range value is set to the default value.

The ranges that you set can overlap. If you have overlapping values, the range field is created as a multivalue field containing all the values that apply. For example, if low=1-10, elevated=5-15, and the input field value is 10, range=low and code=elevated.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

The rangemap command is a distributable streaming command. See Command types.

#### Example 1:

Set range to "green" if the date_second is between 1-30; "blue", if between 31-39; "red", if between 40-59; and "gray", if no range matches (for example, if date_second=0).

#### Example 2:

Sets the value of each event's range field to "low" if its count field is 0 (zero); "elevated", if between 1-100; "severe", otherwise.

| This example uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), etc., for each earthquake recorded.

You can download a current CSV file from the USGS Earthquake Feeds and add it as an input. The following examples uses the All Earthquakes under the Past 30 days list. |

This search counts the number and magnitude of each earthquake that occurred in and around Alaska. Then a  color is assigned to each magnitude using the rangemap command.

| magnitude | count | range |
| --- | --- | --- |
| 3.7 | 15 | weak |
| 3.8 | 31 | weak |
| 3.9 | 29 | light |
| 4 | 22 | light |
| 4.1 | 30 | light |
| 4.2 | 15 | light |
| 4.3 | 10 | light |
| 4.4 | 22 | strong |
| 4.5 | 3 | strong |
| 4.6 | 8 | strong |
| 4.7 | 9 | strong |
| 4.8 | 6 | strong |
| 4.9 | 6 | strong |
| 5 | 2 | severe |
| 5.1 | 2 | severe |
| 5.2 | 5 | severe |

#### Summarize the results by range value

The results look something like this:

| range | sum(count) |
| --- | --- |
| gray | 127 |
| green | 96 |
| red | 23 |
| yellow | 43 |

#### Arrange the results in a custom sort order

By default the values in the search results are in descending order by the sum(count) field. You can apply a custom sort order to the results using the eval command with the case function.

The results look something like this:

| range | sum(count) | sort_field |
| --- | --- | --- |
| red | 23 | 1 |
| yellow | 43 | 2 |
| green | 96 | 3 |
| gray | 127 | 4 |
 