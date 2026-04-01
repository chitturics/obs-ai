---
 command: sort
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/sort
 title: sort
 download_date: 2026-02-03 09:17:38
---

 # sort

The sort command sorts all of the results by the specified fields. Results missing a given field are treated as having the smallest or largest possible value of that field if the order is descending or ascending, respectively.

If the first argument to the sort command is a number, then at most that many results are returned, in order. If no number is specified, the default limit of 10000 is used. If the number 0 is specified, all of the results are returned. See the count argument for more information.

The required syntax is in bold.

#### Required arguments

#### Optional arguments

#### Sort field options

The sort command is a dataset processing command. See Command types.

By default, sort tries to automatically determine what it is sorting. If the field contains numeric values, the collating sequence is numeric. If the field contains on IP address values, the collating sequence is for IP addresses. Otherwise, the collating sequence is in lexicographical order. Some specific examples are:

- Alphabetic strings are sorted lexicographically.
- Punctuation strings are sorted lexicographically.
- Numeric data is sorted as you would expect for numbers and the sort order is specified as ascending or descending.
- Alphanumeric strings are sorted based on the data type of the first character. If the string starts with a number, the string is sorted numerically based on that number alone. Otherwise, strings are sorted lexicographically.
- Strings that are a combination of alphanumeric and punctuation characters are sorted the same way as alphanumeric strings.

The sort order is determined between each pair of values that are compared at any one time. This means that for some pairs of values, the order might be lexicographical, while for other pairs the order might be numerical.

| Results in descending order | Description |
| --- | --- |
| 10.1
9.1 | This set of values are sorted numerically because the values are all numeric. |
| 9.1.a
10.1.a | This set of values are sorted lexicographically because the values are alphanumeric strings. |

#### Lexicographical order

Lexicographical order sorts items based on the values used to encode the items in computer memory. In Splunk software, this is almost always UTF-8 encoding, which is a superset of ASCII.

- Numbers are sorted before letters. Numbers are sorted based on the first digit. For example, the numbers 10, 9, 70, 100 are sorted lexicographically as 10, 100, 70, 9.
- Uppercase letters are sorted before lowercase letters.
- Symbols are not standard. Some symbols are sorted before numeric values. Other symbols are sorted before or after letters.

#### Custom sort order

You can specify a custom sort order that overrides the lexicographical order. See the blog Order Up! Custom Sort Orders.

#### 1. Use the sort field options to specify field types

Sort the results by the ipaddress field in ascending order and then sort by the url field in descending order.

#### 2. Specifying the number of results to sort

Sort first 100 results in descending order of the "size" field and then by the "source" value in ascending order. This example specifies the type of data in each of the fields.  The "size" field contains numbers and the "source" field contains strings.

#### 3. Specifying descending and ascending sort orders

Sort results by the "_time" field in ascending order and then by the "host" value in descending order.

#### 4. Changing the time format of events for sorting

Change the format of the event's time and sort the results in descending order by the Time field that is created with the eval command.

(Thanks to Splunk user Ayn for this example.)

#### 5. Return the most recent event

Return the most recent event:

#### 6. Use a label with the <count>

You can use a label to identify the number of results to return:
Return the first 12 results, sorted by the "host" field in descending order.

#### 1. Specify a custom sort order

Sort a table of results in a specific order, such as days of the week or months of the year, that is not lexicographical or numeric. For example, suppose you have a search that produces the following table:

| Day | Total |
| --- | --- |
| Friday | 120 |
| Monday | 93 |
| Tuesday | 124 |
| Thursday | 356 |
| Weekend | 1022 |
| Wednesday | 248 |

Sorting on the day field (Day) returns a table sorted alphabetically, which does not make much sense. Instead, you want to sort the table by the day of the week, Monday to Friday, with the Weekend at the end of the list.

To create a custom sort order, you first need to create a field called sort_field that defines the order. Then you can sort on that field.

This search uses the eval command to create the sort_field and the fields command to remove sort_field from the final results table.

The results look something like this:

| Day | Total |
| --- | --- |
| Monday | 93 |
| Tuesday | 124 |
| Wednesday | 248 |
| Thursday | 356 |
| Friday | 120 |
| Weekend | 1022 |

(Thanks to Splunk users Ant1D and Ziegfried for this example.)

For additional custom sort order examples, see the blog 
Order Up! Custom Sort Orders and the Extended example in the rangemap command.
 