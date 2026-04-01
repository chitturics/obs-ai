---
 command: convert
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/convert
 title: convert
 download_date: 2026-02-03 09:03:47
---

 # convert

The convert command converts field values in your search results into numerical values. Unless you use the AS clause, the original values are replaced by the new values.

Alternatively, you can use evaluation functions such as strftime(), strptime(), or tonumber() to convert field values.

convert [timeformat=string] (<convert-function> [AS <field>] )...

#### Required arguments

#### Optional arguments

#### Convert functions

The convert command is a distributable streaming command. See Command types.

#### 1. Convert all field values to numeric values

Use the auto convert function to convert all field values to numeric values.

#### 2. Convert field values except for values in specified fields

Convert every field value to a number value except for values in the field src_ip. Use the none convert function to specify fields to ignore.

#### 3. Change the duration values to seconds for the specified fields

Change the duration values to seconds for the specified fields

#### 4. Change the sendmail syslog duration format to seconds

Change the sendmail syslog duration format (D+HH:MM:SS) to seconds. For example, if delay="00:10:15", the resulting value is delay="615".
This example uses the dur2sec convert function.

#### 5. Convert field values that contain numeric and string values

Convert the values in the duration field, which contain numeric and string values, to numeric values by removing the string portion of the values. For example, if duration="212 sec", the resulting value is duration="212". This example uses the rmunit convert function.

#### 6. Change memory values to kilobytes

Change all memory values in the virt field to KBs.
This example uses the memk convert function.

#### 1. Convert a UNIX time to a more readable time format

Convert a UNIX time to a more readable time formatted to show hours, minutes, and seconds.

source="all_month.csv" | convert timeformat="%H:%M:%S" ctime(_time) AS c_time | table _time, c_time

- The ctime() function converts the _time value in the CSV file events to the format specified by the timeformat argument.
- The timeformat="%H:%M:%S" argument tells the search to format the _time value as HH:MM:SS.
- The converted time ctime field is renamed c_time.
- The table command is used to show the original _time value and the ctime field.

The results appear on the Statistics tab and look something like this:

| _time | c_time |
| --- | --- |
| 2018-03-27 17:20:14.839 | 17:20:14 |
| 2018-03-27 17:21:05.724 | 17:21:05 |
| 2018-03-27 17:27:03.790 | 17:27:03 |
| 2018-03-27 17:28:41.869 | 17:28:41 |
| 2018-03-27 17:34:40.900 | 17:34:40 |
| 2018-03-27 17:38:47.120 | 17:38:47 |
| 2018-03-27 17:40:10.345 | 17:40:10 |
| 2018-03-27 17:41:55.548 | 17:41:55 |

The ctime() function changes the timestamp to a non-numerical value. This is useful for display in a report or for readability in your events list.

#### 2. Convert a time in MM:SS.SSS to a number in seconds

Convert a time in MM:SS.SSS (minutes, seconds, and subseconds) to a number in seconds.

sourcetype=syslog | convert mstime(_time) AS ms_time | table _time, ms_time

- The mstime() function converts the _time field values from a minutes and seconds to just seconds.

The converted time field is renamed ms_time.

- The table command is used to show the original _time value and the converted time.

| _time | ms_time |
| --- | --- |
| 2018-03-27 17:20:14.839 | 1522196414.839 |
| 2018-03-27 17:21:05.724 | 1522196465.724 |
| 2018-03-27 17:27:03.790 | 1522196823.790 |
| 2018-03-27 17:28:41.869 | 1522196921.869 |
| 2018-03-27 17:34:40.900 | 1522197280.900 |
| 2018-03-27 17:38:47.120 | 1522197527.120 |
| 2018-03-27 17:40:10.345 | 1522197610.345 |
| 2018-03-27 17:41:55.548 | 1522197715.548 |

The mstime() function changes the timestamp to a numerical value. This is useful if you want to use it for more calculations.

#### 3. Convert a string time in HH:MM:SS into a number

Convert a string field time_elapsed that contains times in the format HH:MM:SS into a number. Sum the time_elapsed by the user_id field.  This example uses the eval command to convert the converted results from seconds into minutes.

...| convert num(time_elapsed) | stats sum(eval(time_elapsed/60)) AS Minutes BY user_id
 