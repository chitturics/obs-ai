---
 command: fieldformat
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/fieldformat
 title: fieldformat
 download_date: 2026-02-03 09:06:33
---

 # fieldformat

With the fieldformat command you can use an <eval-expression> to change the format of a field value when the results render. This command changes the appearance of the results without changing the underlying value of the field.

Because commands that come later in the search pipeline cannot modify the formatted results, use the fieldformat command as late in the search pipeline as possible.

The fieldformat command does not apply to commands that export data, such as the outputcsv and outputlookup commands. The export retains the original data format and not the rendered format. If you want the format to apply to exported data, use the eval command instead of the fieldformat command.

fieldformat <field>=<eval-expression>

#### Required arguments

For more information, see the eval command.

The fieldformat command is a distributable streaming command. See Command types.

Time format variables are frequently used with the fieldformat command. See Date and time format variables.

#### Functions

You can use a wide range of functions with the fieldformat command. For general information about using functions, see  Evaluation functions.

The following table lists the supported functions by type of function. Use the links in the table to learn more about each function, and to see examples.

| Type of function | Supported functions and syntax |  |  |
| --- | --- | --- | --- |
| Comparison and Conditional functions | case(X,"Y",...)

cidrmatch("X",Y)

coalesce(X,...)

false()

if(X,Y,Z) | in(VALUE-LIST)

like(TEXT, PATTERN)

match(SUBJECT, "REGEX")

null() | nullif(X,Y)

searchmatch(X)

true()

validate(X,Y,...) |
| Conversion functions | printf("format",arguments) | tonumber(NUMSTR,BASE) | tostring(X,Y) |
| Cryptographic functions | md5(X)

sha1(X) | sha256(X) | sha512(X) |
| Date and Time functions | now()

relative_time(X,Y) | strftime(X,Y)

strptime(X,Y) | time() |
| Informational functions | isbool(X)

isint(X)

isnotnull(X) | isnull(X)

isnum(X) | isstr(X)

typeof(X) |
| Mathematical functions | abs(X)

ceiling(X)

exact(X)

exp(X) | floor(X)

ln(X)

log(X,Y)

pi() | pow(X,Y)

round(X,Y)

sigfig(X)

sqrt(X) |
| Multivalue eval functions | commands(X)

mvappend(X,...)

mvcount(MVFIELD)

mvdedup(X) | mvfilter(X)

mvfind(MVFIELD,"REGEX")

mvindex(MVFIELD,STARTINDEX,ENDINDEX)

mvjoin(MVFIELD,STR) | mvrange(X,Y,Z)

mvsort(X)

mvzip(X,Y,"Z") |
| Statistical eval functions | max(X,...) | min(X,...) | random() |
| Text functions | len(X)

lower(X)

ltrim(X,Y)

replace(X,Y,Z) | rtrim(X,Y)

spath(X,Y)

split(X,"Y")

substr(X,Y,Z) | trim(X,Y)

upper(X)

urldecode(X) |
| Trigonometry and Hyperbolic functions | acos(X)

acosh(X)

asin(X)

asinh(X)

atan(X) | atan2(X,Y)

atanh(X)

cos(X)

cosh(X)

hypot(X,Y) | sin(X)

sinh(X)

tan(X)

tanh(X) |

#### 1. Format numeric values to display commas

This example uses the metadata command to return results for the sourcetypes in the main index.

| metadata type=sourcetypes 
| table sourcetype totalCount

The metadata command returns many fields. The table command is used to return only the sourcetype and totalCount fields.

The results appear on the Statistics tab and look like this:

| sourcetype | totalCount |
| --- | --- |
| access_combined_wcookie | 39532 |
| cisco:esa | 112421 |
| csv | 9510 |
| secure | 40088 |
| vendor_sales | 30244 |

```
fieldformat
```

```
totalCount
```

| metadata type=sourcetypes 
| table sourcetype totalCount
| fieldformat totalCount=tostring(totalCount, "commas")

The results appear on the Statistics tab and look something like this:

| sourcetype | totalCount |
| --- | --- |
| access_combined _wcookie | 39,532 |
| cisco:esa | 112,421 |
| csv | 9,510 |
| secure | 40,088 |
| vendor_sales | 30,244 |

#### 2. Display UNIX time in a readable format

Assume that the start_time field contains UNIX time. Format the start_time field to display only the hours, minutes, and seconds that correspond to the UNIX time.

... | fieldformat start_time = strftime(start_time, "%H:%M:%S")

#### 3. Add currency symbols to numerical values

To format numerical values in a field with a currency symbol, you must specify the symbol as a literal and enclose it in quotation marks. Use a period character as a binary concatenation operator, followed by the tostring function, which enables you to display commas in the currency values.

...| fieldformat totalSales="$".tostring(totalSales,"commas")

#### 1. Formatting multiple fields

This example shows how to change the appearance of search results to display commas in numerical values and dates into readable formats.

First, use the metadata command to return results for the sourcetypes in the main index.

|metadata type=sourcetypes | table sourcetype totalCount |fieldformat totalCount=tostring(totalCount, "commas")

| metadata type=sourcetypes 
| rename totalCount as Count firstTime as "First Event" lastTime as "Last Event" 
  recentTime as "Last Update" 
| table sourcetype Count "First Event" "Last Event" "Last Update"

- The metadata command returns the fields firstTime, lastTime, recentTime, totalCount, and type.
- In addition, because the search specifies types=sourcetypes, a field called sourcetype is also returned.
- The  totalCount, firstTime, lastTime, and recentTime fields are renamed to Count, First Event, Last Event, and Last Update.
- The First Event, Last Event, and Last Update fields display the values in UNIX time.

The results appear on the Statistics tab and look something like this:

| sourcetype | Count | First Event | Last Event | Last Update |
| --- | --- | --- | --- | --- |
| access_combined_wcookie | 39532 | 1520904136 | 1524014536 | 1524067875 |
| cisco:esa | 112421 | 1521501480 | 1521515900 | 1523471156 |
| csv | 9510 | 1520307602 | 1523296313 | 1523392090 |
| secure | 40088 | 1520838901 | 1523949306 | 1524067876 |
| vendor_sales | 30244 | 1520904187 | 1524014642 | 1524067875 |

```
fieldformat
```

```
Count
```

```
First Event
```

```
Last Event
```

```
Last Update
```

| metadata type=sourcetypes 
| rename totalCount as Count firstTime as "First Event" lastTime as "Last Event" 
  recentTime as "Last Update" 
| table sourcetype Count "First Event" "Last Event" "Last Update" 
| fieldformat Count=tostring(Count, "commas") 
| fieldformat "First Event"=strftime('First Event', "%c") 
| fieldformat "Last Event"=strftime('Last Event', "%c") 
| fieldformat "Last Update"=strftime('Last Update', "%c")

The results appear on the Statistics tab and look something like this:

| sourcetype | Count | First Event | Last Event | Last Update |
| --- | --- | --- | --- | --- |
| access_combined _wcookie | 39,532 | Mon Mar 12 18:22:16 2018 | Tue Apr 17 18:22:16 2018 | Wed Apr 18 09:11:15 2018 |
| cisco:esa | 112,421 | Mon Mar 19 16:18:00 2018 | Mon Mar 19 20:18:20 2018 | Wed Apr 11 11:25:56 2018 |
| csv | 9,510 | Mon Mar 5 19:40:02 2018 | Mon Apr 9 10:51:53 2018 | Tue Apr 10 13:28:10 2018 |
| secure | 40,088 | Mon Mar 12 00:15:01 2018 | Tue Apr 17 00:15:06 2018 | Wed Apr 18 09:11:16 2018 |
| vendor_sales | 30,244 | Mon Mar 12 18:23:07 2018 | Tue Apr 17 18:24:02 2018 | Wed Apr 18 09:11:15 2018 |

eval, where

Date and time format variables
 