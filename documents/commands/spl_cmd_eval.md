---
 command: eval
 source_url: https://help.splunk.com/en/splunk-enterprise/search/spl-search-reference/9.4/search-commands/eval
 title: eval
 download_date: 2026-02-03 09:05:52
---

 # eval

The eval command calculates an expression and puts the resulting value into a search results field.

- If the field name that you specify does not match a field in the output, a new field is added to the search results.
- If the field name that you specify matches a field name that already exists in the search results, the results of the eval expression overwrite the values in that field.

The eval command evaluates mathematical, string, and boolean expressions.

You can chain multiple eval expressions in one search using a comma to separate subsequent expressions. The search processes multiple eval expressions left-to-right and lets you reference previously evaluated fields in subsequent expressions.

#### Difference between eval and stats commands

The stats command calculates statistics based on fields in your events. The eval command creates new fields in your events by using existing fields and an arbitrary expression.

eval <field>=<expression>[","  <field>=<expression>]...

#### Required arguments

The eval command is a distributable streaming command. See Command types.

#### General

You must specify a field name for the results that are returned from your eval command expression. You can specify a name for a new field or for an existing field.

CAUTION: If the field name that you specify matches an existing field name, the values in the existing field are replaced by the results of the eval expression.

Numbers and strings can be assigned to fields, while booleans cannot be assigned.  However you can convert booleans and nulls to strings using the tostring() function, which can be assigned to fields.

If you are using a search as an argument to the eval command and functions, you cannot use a saved search name; you must pass a literal search string or a field that contains a literal search string (like the 'search' field extracted from index=_audit events).

#### Numeric calculations

During calculations, numbers are treated as double-precision floating-point numbers, subject to all the usual behaviors of floating point numbers. If the calculation results in the floating-point special value NaN (Not a Number), it is represented as "nan" in your results. The special values for positive and negative infinity are represented in your results as "inf" and "-inf" respectively. Division by zero results in a null field.

See the isnum and the isstr functions in Informational functions.

#### Rounding

Results are rounded to a precision appropriate to the precision of the input results. The precision of the results can be no greater than the precision of the least-precise input. For example, the following search has different precision for 0.2 in each of the calculations based on the number of zeros following the number 2:

The results look like this:

| _time | decimal1 | decimal2 | decimal3 | exact |
| --- | --- | --- | --- | --- |
| 2022-09-02 21:53:30 | 2 | 1.7 | 1.65 | 1.650 |

If you want to return an arbitrary number of digits of precision, use the exact function, as shown in the last calculation in the search. See the exact evaluation function.

#### Long numbers

There are situations where the results of a calculation contain more digits than can be represented by a floating- point number. In those situations precision might be lost on the least significant digits. The limit to precision is 17 significant digits, or  -253 +1 to 253 -1.

#### Significant digits

If a result returns a long number with more digits than you want to use, you can specify the number of digits to return using the sigfig function.  See Example 2 under the basic examples for the sigfig(X) function.

#### Supported functions

You can use a wide range of functions with the eval command. For general information about using functions, see  Evaluation functions.

- For a list of functions by category, see Function list by category.
- For an alphabetical list of functions, see Alphabetical list of functions.

#### Operators

The following table lists the basic operations you can perform with the eval command. For these evaluations to work, the values need to be valid for the type of operation. For example, with the exception of addition, arithmetic operations might not produce valid results if the values are not numerical. When concatenating values, Splunk  software reads the values as strings, regardless of the value.

| Type | Operators |
| --- | --- |
| Arithmetic | + - * / % |
| Concatenation | . |
| Boolean | AND OR NOT XOR < > <= >= != = == LIKE |

#### Operators that produce numbers

- The plus ( + ) operator accepts two numbers for addition, or two strings for concatenation.
- The subtraction ( - ), multiplication ( * ), division ( / ), and modulus ( % ) operators accept two numbers.

#### Operators that produce strings

- The period ( . ) operator concatenates both strings and number.  Numbers are concatenated in their string represented form.

#### Operators that produce booleans

- The AND, OR, and XOR operators accept two Boolean values.
- The <, >, <=, >=, !=, =, and == operators accept two numbers or two strings.
- In expressions, the single equal sign ( = ) is a synonym for the double equal sign ( == ).
- The LIKE operator accepts two strings.  This is a pattern match similar to what is used in SQL. For example string LIKE pattern.  The pattern operator supports literal text, a percent ( % ) character for a wildcard, and an underscore ( _ ) character for a single character match.  For example, field LIKE "a%b_" matches any string starting with a, followed by anything, followed by b, followed by one character.

#### The = and == operators

In expressions, the single equal sign (  = ) and the double equal sign (  == ) are synonymous. Although you can use these operators interchangeably in your searches to make assignments or comparisons, keep the following conventions in mind when you create your searches:

- The = operator means either "is equal to" or "is assigned to", depending on the context. This operator is typically used to assign a value to a field.

- The == operator means "is equal to". This operator is typically used to compare 2 values.

For example, in the following search, = is used to assign the description to the case expression, and == is used to indicate status is equal to specific error codes.

#### Boolean expressions

The order in which Boolean expressions are evaluated with the eval command is:

- Expressions within parentheses
- NOT clauses
- AND clauses
- OR clauses
- XOR clauses

This evaluation order is different than the order used with the search command, which evaluates OR before AND clauses, and doesn't support XOR.

See Boolean expressions with logical operators in the Splunk platform Search Manual.

#### Field names

To specify a field name with multiple words, you can either concatenate the words, or use single quotation marks when you specify the name. For example, to specify the field name Account ID you can specify AccountID or 'Account ID'.

To specify a field name with special characters, such as a period, use single quotation marks. For example, to specify the field name Last.Name use  'Last.Name'.

When assigning the value of a field to the value of another field, do not use leading spaces in the field name. However, you can use spaces at the end of the field name. For example, a search like this that assigns the same value to fields called first   and second produces valid results, even though first   has a trailing space:

However, the following search does not produce valid results because    first has a leading space:

#### Dynamic field name creation

You can use the value of one field as the name of another field by using curly braces ( { } ), which dynamically creates a field name on the left side of an eval expression. For example, if you have an event with the aName=counter and aValue=1234 fields, use | eval {aName}=aValue to return counter=1234.

Searches that dynamically create field names generate errors and do not complete if there are unbounded recursive replacements. For example, the following search doesn't produce results because the right side of the eval expression generates bracketed field names that are recursive. In this case, {p} replaces the value of p in the fieldname, so v_{p} becomes v_{p} over and over again, in a recursive loop.

The following search produces valid results because the value of one field is not recursively used as the name of another field.

The search results look something like this:

| _time | counter | field1 |
| --- | --- | --- |
| 2023-05-10 21:15:49 | 1234 | counter |

#### Calculated fields

You can use eval statements to define calculated fields by defining the eval statement in props.conf. If you are using Splunk Cloud Platform, you can define calculated fields using Splunk Web, by choosing Settings > Fields > Calculated Fields. When you run a search, Splunk software evaluates the statements and creates fields in a manner similar to that of search time field extraction. Setting up calculated fields means that you no longer need to define the eval statement in a search string. Instead, you can search on the resulting calculated field directly.

You can use calculated fields to move your commonly used eval statements out of your search string and into props.conf, where they will be processed behind the scenes at search time. With calculated fields, you can change the search from:

to this search:

In this example, the three eval statements that were in the search--that defined the accountname, from_user, and from_domain fields--are now computed behind the scenes when the search is run for any event that contains the extracted field mailfrom field. You can also search on those fields independently once they're set up as calculated fields in props.conf. You could search on from_domain=email.com, for example.

For more information about calculated fields, see About calculated fields in the Knowledge Manager Manual.

#### Search event tokens

If you are using the eval command in search event tokens, some of the evaluation functions might be unavailable or have a different behavior. See Custom logic for search tokens in Dashboards and Visualizations for information about the evaluation functions that you can use with search event tokens.

#### 1. Create a new field that contains the result of a calculation

Create a new field called velocity in each event. Calculate the velocity by dividing the values in the distance field by the values in the time field.

#### 2. Use the if function to analyze field values

Create a field called error in each event. Using the if function, set the value in the error field to OK if the status value is 200. Otherwise set the error field value to Problem.

... | eval error = if(status == 200, "OK", "Problem")

#### 3. Convert values to lowercase

Create a new field in each event called low-user. Using the lower  function, populate the field with the lowercase version of the values in the username field.

#### 4. Use the value of one field as the name for a new field

In this example, use each value of the field counter to make a new field name. Assign to the new field the value of the Value field.  See Field names under the Usage section.

index=perfmon sourcetype=Perfmon* counter=* Value=* | eval {counter} = Value

#### 5. Set sum_of_areas to be the sum of the areas of two circles

... | eval sum_of_areas = pi() * pow(radius_a, 2) + pi() * pow(radius_b, 2)

#### 6. Set status to some simple http error codes

... | eval error_msg = case(error == 404, "Not found", error == 500, "Internal Server Error", error == 200, "OK")

#### 7. Concatenate values from two fields

Use the period ( . ) character to concatenate the values in  first_name field with the values in the last_name field. Quotation marks are used to insert a space character between the two names. When concatenating, the values are read as strings, regardless of the actual value.

#### 8. Separate multiple eval operations with a comma

You can specify multiple eval operations by using a comma to separate the operations. In the following search the full_name evaluation uses the period ( . ) character to concatenate the values in the first_name field with the values in the last_name field. The low_name evaluation uses the lower function to convert the full_name evaluation into lowercase.

... | eval full_name = first_name." ".last_name, low_name = lower(full_name)

#### 9. Convert a numeric field value to a string with commas and 2 decimals

If the original value of x is 1000000.1278, the following search returns x as 1,000,000.13. The tostring function returns only two decimal places with the decimals rounded up or down depending on the values.

To include a currency symbol at the beginning of the string:

This returns x as $1,000,000.13

#### 10. Rounding with values outside of the range of supported values

The range of values supported in Splunk searches is 0 to 253 -1. This example demonstrates the differences in results you get when you use values in eval expressions that fall outside of the range of supported values.

| makeresults | eval max_supported_val = pow(2, 53)-1, val1 = max_supported_val + 1, val2 = max_supported_val + 2

The results look like this:

| _time | max_supported_val | val1 | val2 |
| --- | --- | --- | --- |
| 2022-09-04  10:22:11 | 9007199254740991 | 9007199254740992 | 9007199254740992 |

As you can see, because val1 and val2 are beyond the range of supported values, the results are the same even though they should be different. This is because of rounding on those values that are outside of the supported range of values.

#### 1. Coalesce a field from two different source types, create a transaction of events

This example shows how you might coalesce a field from two different source types and use that to create a transaction of events. sourcetype=A has a field called number, and sourcetype=B has the same information in a field called subscriberNumber.

sourcetype=A OR sourcetype=B | eval phone=coalesce(number,subscriberNumber) | transaction phone maxspan=2m

The eval command is used to add a common field, called phone, to each of the events whether they are from sourcetype=A or sourcetype=B. The value of phone is defined, using the coalesce() function, as the values of number and subscriberNumber. The coalesce() function takes the value of the first non-NULL field (that means, it exists in the event).

Now, you're able to group events from either source type A or B if they share the same phone value.

#### 2. Separate events into categories, count and display minimum and maximum values

| This example uses recent earthquake data downloaded from the USGS Earthquakes website. The data is a comma separated ASCII text file that contains magnitude (mag), coordinates (latitude, longitude), region (place), and so forth, for each earthquake recorded.
You can download a current CSV file from the USGS Earthquake Feeds and upload the file to your Splunk instance if you want follow along with this example. |

Earthquakes occurring at a depth of less than 70 km are classified as shallow-focus earthquakes, while those with a focal-depth between 70 and 300 km are commonly termed mid-focus earthquakes. In subduction zones, deep-focus earthquakes may occur at much greater depths (ranging from 300 up to 700 kilometers).

To classify recent earthquakes based on their depth, you use the following search.

source=all_month.csv | eval Description=case(depth<=70, "Shallow", depth>70 AND depth<=300, "Mid", depth>300, "Deep") | stats count min(mag) max(mag) by Description

The eval command is used to create a field called Description, which takes the value of "Shallow", "Mid", or "Deep" based on the Depth of the earthquake. The case() function is used to specify which ranges of the depth fits each description. For example, if the depth is less than 70 km, the earthquake is characterized as a shallow-focus quake; and the resulting Description is Shallow.

The search also pipes the results of the eval command into the stats command to count the number of earthquakes and display the minimum and maximum magnitudes for each Description.

The results appear on the Statistics tab and look something like this:

| Description | count | min(Mag) | max(Mag) |
| --- | --- | --- | --- |
| Deep | 35 | 4.1 | 6.7 |
| Mid | 635 | 0.8 | 6.3 |
| Shallow | 6236 | -0.60 | 7.70 |

#### 3. Find IP addresses and categorize by network using eval functions cidrmatch and if

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

In this search, you're finding IP addresses and classifying the network they belong to.

sourcetype=access_* | eval network=if(cidrmatch("182.236.164.11/16", clientip), "local", "other")

This example uses the cidrmatch() function to compare the IP addresses in the clientip field to a subnet range. The search also uses the if() function, which says that if the value of clientip falls in the subnet range, then the network field value is  local. Otherwise, network=other.

The eval command does not do any special formatting to your results. The command creates a new field based on the eval expression you specify.

In the fields sidebar, click on the network field. In the popup, next to Selected click Yes and close the popup. Now you can see, inline with your search results, which IP addresses are part of your local network and which are not. Your events list looks something like this:

Another option for formatting your results is to pipe the results of eval to the table command to display only the fields of interest to you.

Note: This example just illustrates how to use the cidrmatch function. If you want to classify your events and quickly search for those events, the better approach is to use event types. Read more about event types in the Knowledge manager manual.

#### 4. Extract information from an event into a separate field, create a multivalue field

| This example uses sample email data. You should be able to run this search on any email data by replacing the sourcetype=cisco:esa with the sourcetype value and the mailfrom field with email address field name in your data. For example, the email might be To, From, or Cc). |

Use the email address field to extract the name and domain. The eval command in this search contains multiple expressions, separated by commas.

sourcetype="cisco:esa" mailfrom=* | eval accountname=split(mailfrom,"@"), from_user=mvindex(accountname,0), from_domain=mvindex(accountname,-1) | table mailfrom, from_user, from_domain

- The split() function is used to break the mailfrom field into a multivalue field called accountname. The first value of accountname is everything before the "@" symbol, and the second value is everything after.
- The mvindex() function is used to set from_user to the first value in accountname and to set from_domain to the second value in accountname.
- The results of the eval expressions are then piped into the table command.

You can see the the original mailfrom values and the new from_user and from_domain values in the results table. The results appear on the Statistics tab and look something like this:

| mailfrom | from_user | from_domain |
| --- | --- | --- |
| na.lui@sample.net | na.lui | sample.net |
| MAILER-DAEMON@hcp2mailsec.sample.net | MAILER-DAEMON | hcp2mailsec.sample.net |
| M&MService@example.com | M&MService | example.com |
| AlexMartin@oursample.de | AlexMartin | oursample.de |
| Exit_Desk@sample.net | Exit_Desk | sample.net |
| buttercup-forum+SEMAG8PUC4RETTUB@groups.com | buttercup-forum+SEMAG8PUC4RETTUB | groups.com |
| eduardo.rodriguez@sample.net | eduardo.rodriguez | sample.net |
| VC00110489@techexamples.com | VC00110489 | techexamples.com |

Note: This example was written to demonstrate how to use an eval function to identify the individual values of a multivalue fields. Because this particular set of email data did not have any multivalue fields, the example creates a multivalue filed,  accountname, from a single value field, mailfrom.

#### 5. Categorize events using the match function

| This example uses sample email data. You should be able to run this search on any email data by replacing the sourcetype=cisco:esa with the sourcetype value and the mailfrom field with email address field name in your data. For example, the email might be To, From, or Cc). |

This example classifies where an email came from based on the email address domain. The .com, .net, and .org  addresses are considered local, while anything else is considered abroad. There are many domain names. Of course, domains that are not .com, .net, or .org are not necessarily from abroad. This is just an example.

The eval command in this search contains multiple expressions, separated by commas.

sourcetype="cisco:esa" mailfrom=*| eval accountname=split(mailfrom,"@"),  from_domain=mvindex(accountname,-1), location=if(match(from_domain, "[^\n\r\s]+\.(com|net|org)"), "local", "abroad") | stats count BY location

The first half of this search is similar to previous example. The split() function is used to break up the email address in the mailfrom field. The mvindex function defines the from_domain as the portion of the mailfrom field after the @ symbol.

Then, the if() and match() functions are used.

- If the from_domain value ends with a .com, .net., or .org, the location field is assigned the value local.
- If from_domain does not match, location is assigned the value abroad.

The eval results are then piped into the stats command to count the number of results for each location value.

The results appear on the Statistics tab and look something like this:

| location | count |
| --- | --- |
| abroad | 3543 |
| local | 14136 |

Note: This example merely illustrates using the match() function. If you want to classify your events and quickly search for those events, the better approach is to use event types. Read more about event types in the Knowledge manager manual.

#### 6.  Convert the duration of transactions into more readable string formats

| This example uses the sample data from the Search Tutorial but should work with any format of Apache web access log. To try this example on your own Splunk instance, you must download the sample data and follow the instructions to get the tutorial data into Splunk. Use the time range All time when you run the search. |

When you use the transaction command, as shown in the following search, it calculates the length of time for the transaction. A new field, called duration, is automatically added to the results. The duration is the time between the first and last events in the transaction.

sourcetype=access_* | transaction clientip maxspan=10m

In the Interesting fields list, click on the duration  field to see the top 10 values for duration.  The values are displayed in seconds. Click Yes to add the field to the Selected fields list.

You can use the eval command to reformat a numeric field into a more readable string format. The following search uses the tostring() function with the "duration" option to convert the values in the duration field into a string formatted as HH:MM:SS.

sourcetype=access_* | transaction clientip maxspan=10m | eval durationstr=tostring(duration,"duration")

The search defines a new field, durationstr, for the reformatted duration values. In the Interesting fields list, click on the durationstr field and select Yes to add the field to the Selected fields list. The values for the fields now appear in the set of fields below each transaction. The following image shows how your search results should look:
 