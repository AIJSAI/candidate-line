Source: https://docs.aws.amazon.com/general/latest/gr/transcribe.md
Read (UTC): 2026-11-02T00:01:40Z
HTTP: 200



# Amazon Transcribe endpoints and quotas
<a name="transcribe"></a>

To connect programmatically to an AWS service, you use an endpoint. AWS services offer the following endpoint types in some or all of the AWS Regions that the service supports: IPv4 endpoints, dual-stack endpoints, and FIPS endpoints. Some services provide global endpoints. For more information, see [AWS service endpoints](rande.md).

Service quotas, also referred to as limits, are the maximum number of service resources or operations for your AWS account. For more information, see [AWS service quotas](aws_service_limits.md).

The following are the service endpoints and service quotas for this service.

## Service endpoints
<a name="transcribe_region"></a>

Supported service endpoints differ for batch and streaming transcriptions. In addition, endpoints vary between [Amazon Transcribe](https://docs.aws.amazon.com/transcribe/latest/dg/what-is.html), [Amazon Transcribe Medical](https://docs.aws.amazon.com/transcribe/latest/dg/transcribe-medical.html), and [Amazon Transcribe Call Analytics](https://docs.aws.amazon.com/transcribe/latest/dg/call-analytics.html). Refer to the following tables for details.

The following table shows the supported **batch** endpoints for **Amazon Transcribe**.


| Region Name | Region | Endpoint | Protocol | 
| --- | --- | --- | --- | 
| US East (Ohio) | us-east-2 |  transcribe.us-east-2.amazonaws.com <br /> transcribe.us-east-2.api.aws <br /> fips.transcribe.us-east-2.amazonaws.com <br /> transcribe-fips.us-east-2.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| US East (N. Virginia) | us-east-1 |  transcribe.us-east-1.amazonaws.com <br /> fips.transcribe.us-east-1.amazonaws.com <br /> transcribe-fips.us-east-1.api.aws <br /> transcribe.us-east-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| US West (N. California) | us-west-1 |  transcribe.us-west-1.amazonaws.com <br /> transcribe-fips.us-west-1.api.aws <br /> transcribe.us-west-1.api.aws <br /> fips.transcribe.us-west-1.amazonaws.com  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| US West (Oregon) | us-west-2 |  transcribe.us-west-2.amazonaws.com <br /> fips.transcribe.us-west-2.amazonaws.com <br /> transcribe.us-west-2.api.aws <br /> transcribe-fips.us-west-2.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| Africa (Cape Town) | af-south-1 |  transcribe.af-south-1.amazonaws.com <br /> transcribe.af-south-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Hong Kong) | ap-east-1 |  transcribe.ap-east-1.amazonaws.com <br /> transcribe.ap-east-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Mumbai) | ap-south-1 |  transcribe.ap-south-1.amazonaws.com <br /> transcribe.ap-south-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Seoul) | ap-northeast-2 |  transcribe.ap-northeast-2.amazonaws.com <br /> transcribe.ap-northeast-2.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Singapore) | ap-southeast-1 |  transcribe.ap-southeast-1.amazonaws.com <br /> transcribe.ap-southeast-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Sydney) | ap-southeast-2 |  transcribe.ap-southeast-2.amazonaws.com <br /> transcribe.ap-southeast-2.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Tokyo) | ap-northeast-1 |  transcribe.ap-northeast-1.amazonaws.com <br /> transcribe.ap-northeast-1.api.aws  | HTTPS<br />HTTPS | 
| Canada (Central) | ca-central-1 |  transcribe.ca-central-1.amazonaws.com <br /> transcribe.ca-central-1.api.aws <br /> fips.transcribe.ca-central-1.amazonaws.com <br /> transcribe-fips.ca-central-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| Europe (Frankfurt) | eu-central-1 |  transcribe.eu-central-1.amazonaws.com <br /> transcribe.eu-central-1.api.aws  | HTTPS<br />HTTPS | 
| Europe (Ireland) | eu-west-1 |  transcribe.eu-west-1.amazonaws.com <br /> transcribe.eu-west-1.api.aws  | HTTPS<br />HTTPS | 
| Europe (London) | eu-west-2 |  transcribe.eu-west-2.amazonaws.com <br /> transcribe.eu-west-2.api.aws  | HTTPS<br />HTTPS | 
| Europe (Paris) | eu-west-3 |  transcribe.eu-west-3.amazonaws.com <br /> transcribe.eu-west-3.api.aws  | HTTPS<br />HTTPS | 
| Europe (Stockholm) | eu-north-1 |  transcribe.eu-north-1.amazonaws.com <br /> transcribe.eu-north-1.api.aws  | HTTPS<br />HTTPS | 
| Europe (Zurich) | eu-central-2 |  transcribe.eu-central-2.amazonaws.com <br /> transcribe.eu-central-2.api.aws  | HTTPS<br />HTTPS | 
| Middle East (Bahrain) | me-south-1 |  transcribe.me-south-1.amazonaws.com <br /> transcribe.me-south-1.api.aws  | HTTPS<br />HTTPS | 
| South America (São Paulo) | sa-east-1 |  transcribe.sa-east-1.amazonaws.com <br /> transcribe.sa-east-1.api.aws  | HTTPS<br />HTTPS | 
|  AWS GovCloud (US-East) | us-gov-east-1 |  transcribe.us-gov-east-1.amazonaws.com <br /> transcribe.us-gov-east-1.api.aws <br /> fips.transcribe.us-gov-east-1.amazonaws.com <br /> transcribe-fips.us-gov-east-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
|  AWS GovCloud (US-West) | us-gov-west-1 |  transcribe.us-gov-west-1.amazonaws.com <br /> transcribe-fips.us-gov-west-1.api.aws <br /> fips.transcribe.us-gov-west-1.amazonaws.com <br /> transcribe.us-gov-west-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 

The following table shows the supported **streaming** endpoints for **Amazon Transcribe**.


| Region Name | Region | Endpoint | Protocol | 
| --- | --- | --- | --- | 
| US East (Ohio) | us-east-2 |  transcribestreaming.us-east-2.amazonaws.com <br /> transcribestreaming.us-east-2.api.aws <br /> transcribestreaming-fips.us-east-2.amazonaws.com <br /> transcribestreaming-fips.us-east-2.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| US East (N. Virginia) | us-east-1 |  transcribestreaming.us-east-1.amazonaws.com <br /> transcribestreaming-fips.us-east-1.amazonaws.com <br /> transcribestreaming-fips.us-east-1.api.aws <br /> transcribestreaming.us-east-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| US West (Oregon) | us-west-2 |  transcribestreaming.us-west-2.amazonaws.com <br /> transcribestreaming-fips.us-west-2.amazonaws.com <br /> transcribestreaming.us-west-2.api.aws <br /> transcribestreaming-fips.us-west-2.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| Africa (Cape Town) | af-south-1 |  transcribestreaming.af-south-1.amazonaws.com <br /> transcribestreaming.af-south-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Malaysia) | ap-southeast-5 |  transcribestreaming.ap-southeast-5.amazonaws.com <br /> transcribestreaming.ap-southeast-5.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Mumbai) | ap-south-1 |  transcribestreaming.ap-south-1.amazonaws.com <br /> transcribestreaming.ap-south-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Seoul) | ap-northeast-2 |  transcribestreaming.ap-northeast-2.amazonaws.com <br /> transcribestreaming.ap-northeast-2.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Singapore) | ap-southeast-1 |  transcribestreaming.ap-southeast-1.amazonaws.com <br /> transcribestreaming.ap-southeast-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Sydney) | ap-southeast-2 |  transcribestreaming.ap-southeast-2.amazonaws.com <br /> transcribestreaming.ap-southeast-2.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Thailand) | ap-southeast-7 |  transcribestreaming.ap-southeast-7.amazonaws.com <br /> transcribestreaming.ap-southeast-7.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Tokyo) | ap-northeast-1 |  transcribestreaming.ap-northeast-1.amazonaws.com <br /> transcribestreaming.ap-northeast-1.api.aws  | HTTPS<br />HTTPS | 
| Canada (Central) | ca-central-1 |  transcribestreaming.ca-central-1.amazonaws.com <br /> transcribestreaming.ca-central-1.api.aws <br /> transcribestreaming-fips.ca-central-1.amazonaws.com <br /> transcribestreaming-fips.ca-central-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| Europe (Frankfurt) | eu-central-1 |  transcribestreaming.eu-central-1.amazonaws.com <br /> transcribestreaming.eu-central-1.api.aws  | HTTPS<br />HTTPS | 
| Europe (Ireland) | eu-west-1 |  transcribestreaming.eu-west-1.amazonaws.com <br /> transcribestreaming.eu-west-1.api.aws  | HTTPS<br />HTTPS | 
| Europe (London) | eu-west-2 |  transcribestreaming.eu-west-2.amazonaws.com <br /> transcribestreaming.eu-west-2.api.aws  | HTTPS<br />HTTPS | 
| Europe (Zurich) | eu-central-2 |  transcribestreaming.eu-central-2.amazonaws.com <br /> transcribestreaming.eu-central-2.api.aws  | HTTPS<br />HTTPS | 
| Mexico (Central) | mx-central-1 |  transcribestreaming.mx-central-1.amazonaws.com <br /> transcribestreaming.mx-central-1.api.aws  | HTTPS<br />HTTPS | 
| South America (São Paulo) | sa-east-1 |  transcribestreaming.sa-east-1.amazonaws.com <br /> transcribestreaming.sa-east-1.api.aws  | HTTPS<br />HTTPS | 
|  AWS GovCloud (US-East) | us-gov-east-1 |  transcribestreaming.us-gov-east-1.amazonaws.com <br /> transcribestreaming.us-gov-east-1.api.aws <br /> transcribestreaming-fips.us-gov-east-1.amazonaws.com <br /> transcribestreaming-fips.us-gov-east-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
|  AWS GovCloud (US-West) | us-gov-west-1 |  transcribestreaming.us-gov-west-1.amazonaws.com <br /> transcribestreaming-fips.us-gov-west-1.api.aws <br /> transcribestreaming-fips.us-gov-west-1.amazonaws.com <br /> transcribestreaming.us-gov-west-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 

The following tables show the supported AWS Regions for **Amazon Transcribe Medical** and **Amazon Transcribe Call Analytics**. Note that 'post-call' refers to a batch transcription and 'real-time' refers to a streaming transcription.

To get the endpoints for these Regions, refer to the preceding Amazon Transcribe endpoints tables.


**Amazon Transcribe Medical**  

| **Region** | **Transcription type** | 
| --- | --- | 
| ap-east-1 (Hong Kong) | batch | 
| ap-northeast-1 (Tokyo) | batch, streaming | 
| ap-northeast-2 (Seoul) | batch, streaming | 
| ap-south-1 (Mumbai) | batch | 
| ap-southeast-1 (Singapore) | batch | 
| ap-southeast-2 (Sydney) | batch, streaming | 
| ca-central-1 (Canada, Central) | batch, streaming | 
| eu-central-1 (Frankfurt) | batch, streaming | 
| eu-west-1 (Ireland) | batch, streaming | 
| eu-west-2 (London) | batch, streaming | 
| eu-west-3 (Paris) | batch | 
| me-south-1 (Bahrain) | batch | 
| sa-east-1 (São Paulo) | batch, streaming | 
| us-east-1 (N. Virginia) | batch, streaming | 
| us-east-2 (Ohio) | batch, streaming | 
| us-gov-east-1 (GovCloud, US-East) | batch, streaming | 
| us-gov-west-1 (GovCloud, US-West) | batch, streaming | 
| us-west-1 (San Francisco) | batch | 
| us-west-2 (Oregon) | batch, streaming | 
| eu-north-1 (Stockholm) | batch | 
| af-south-1 (Cape Town) | batch | 


**Amazon Transcribe Call Analytics**  

| **Region** | **Transcription type** | 
| --- | --- | 
| ap-northeast-1 (Tokyo) | post-call, real-time | 
| ap-northeast-2 (Seoul) | post-call, real-time | 
| ap-south-1 (Mumbai) | post-call | 
| ap-southeast-1 (Singapore) | post-call | 
| ap-southeast-2 (Sydney) | post-call, real-time | 
| ca-central-1 (Canada, Central) | post-call, real-time | 
| eu-central-1 (Frankfurt) | post-call, real-time | 
| eu-west-2 (London) | post-call, real-time | 
| us-east-1 (N. Virginia) | post-call, real-time | 
| us-west-2 (Oregon) | post-call, real-time | 

## Service quotas
<a name="limits-amazon-transcribe"></a>


| Name | Default | Adjustable | Description | 
| --- | --- | --- | --- | 
| Channel identification limit | Each supported Region: 2 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-293498CE)  | The maximum number of audio channels that can be identified and extracted from a media file. | 
| Custom medical vocabulary size limit | Each supported Region: 51,200 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-4D1443F5)  | The maximum size of custom medical vocabulary in this account in the current region in bytes. | 
| Custom vocabulary size limit | Each supported Region: 51,200 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-25C67393)  | The maximum size of custom vocabulary in this account in the current region in bytes. | 
| Job queue bandwidth ratio | Each supported Region: 90 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-966BFC39)  | The maximum job queue bandwidth ratio in this account in the current region. | 
| Maximum audio file length | Each supported Region: 28,800 Seconds | No | The maximum length of an audio file in seconds. | 
| Maximum audio file length (Medical) | Each supported Region: 14,400 Seconds | No | The maximum audio file length in seconds (Medical). | 
| Maximum audio file length for Call Analytics batch jobs | Each supported Region: 14,400 Seconds | No | The maximum audio file length (in seconds) for Call Analytics batch jobs. | 
| Maximum audio file length for MedicalScribe jobs | Each supported Region: 5,400 Seconds | No | The maximum audio file length (in seconds) for MedicalScribe jobs. | 
| Maximum audio file size | Each supported Region: 2 Gigabytes | No | The maximum size of an audio file in Gigabytes. | 
| Maximum audio file size (Medical) | Each supported Region: 2 Gigabytes | No | The maximum audio file size (in GB) for medical transcription. | 
| Maximum audio file size for Call Analytics batch jobs | Each supported Region: 500 Megabytes | No | The maximum audio file size (in MB) for Call Analytics batch jobs. | 
| Maximum audio file size for MedicalScribe jobs | Each supported Region: 2 Gigabytes | No | The maximum audio file size (in GB) for MedicalScribe jobs. | 
| Maximum length of a custom vocabulary phrase | Each supported Region: 256 | No | The maximum number of characters in a custom vocabulary phrase. | 
| Maximum number of categories for Call Analytics batch jobs | Each supported Region: 200 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-E3EBEDF2)  | The maximum number of categories per account for Call Analytics batch jobs. | 
| Maximum number of rules per category for Call Analytics batch jobs | Each supported Region: 20 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-2E269322)  | The maximum number of rules per category for Call Analytics batch jobs. | 
| Maximum number of targets allowed per category for Call Analytics batch jobs | Each supported Region: 100 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-3445E3CD)  | The maximum number of targets allowed per category for Call Analytics batch jobs | 
| Maximum number of vocabulary filters | Each supported Region: 100 | No | The maximum number of vocabulary filters from this account in the current Region. | 
| Maximum size of a vocabulary filter | Each supported Region: 50 Kilobytes | No | The maximum size (in KB) of a vocabulary filter. | 
| Minimum audio file duration | Each supported Region: 500 Milliseconds | No | The minimum audio file duration (in ms). | 
| Minimum audio file duration (Medical) | Each supported Region: 500 Milliseconds | No | The minimum audio file duration, in milliseconds (ms) for medical transcription. | 
| Minimum audio file duration for Call Analytics batch jobs | Each supported Region: 500 Milliseconds | No | The minimum audio file duration, in milliseconds (ms), for Call Analytics batch jobs. | 
| Number of channels for channel identification (Medical) | Each supported Region: 2 | No | The maximum number of channels for channel identification (Medical). | 
| Number of channels for channel identification for Call Analytics batch jobs | Each supported Region: 2 | No | The maximum number of channels for channel identification for Call Analytics batch jobs. | 
| Number of concurrent Call Analytics streams (HTTP/2 \+ Websocket) | Each supported Region: 25 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-A34A9084)  | The maximum number of concurrent Call Analytics stream transcription sessions in this account in the current region. | 
| Number of concurrent Medical streams (HTTP/2 \+ Websocket) | Each supported Region: 25 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-D0C82002)  | The maximum number of concurrent Medical stream transcription sessions in this account in the current region. | 
| Number of concurrent MedicalScribe post-stream analytics jobs | Each supported Region: 1 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-D644592E)  | The maximum number of concurrent MedicalScribe post-stream analytics jobs in this account in the current region. | 
| Number of concurrent MedicalScribe streams (HTTP/2) | Each supported Region: 10 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-D2DDB5A5)  | The maximum number of concurrent MedicalScribe stream sessions in this account in the current region. | 
| Number of concurrent analytics jobs | Each supported Region: 100 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-BAA3E542)  | The maximum number of concurrent analytics jobs in this account in the current region. | 
| Number of concurrent language models | Each supported Region: 3 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-B4C1AD62)  | The maximum number of concurrent language models in this account in the current region. | 
| Number of concurrent medical notes jobs | Each supported Region: 5 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-34961B81)  | The maximum number of concurrent medical notes jobs in this account in the current region. | 
| Number of concurrent medical transcription jobs | Each supported Region: 250 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-B882C824)  | The maximum number of concurrent medical transcription jobs in this account in the current region. | 
| Number of concurrent medical vocabulary jobs | Each supported Region: 10 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-9CDB9A91)  | The maximum number of concurrent medical vocabulary jobs in this account in the current region. | 
| Number of concurrent streams (HTTP/2 \+ Websocket) | Each supported Region: 25 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-0599F82B)  | The maximum number of concurrent stream transcription sessions in this account in the current region. | 
| Number of concurrent transcription jobs | Each supported Region: 250 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-58D7221C)  | The maximum number of concurrent transcription jobs in this account in the current region. | 
| Number of concurrent vocabulary jobs | Each supported Region: 10 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-0E2548E4)  | The maximum number of concurrent vocabulary jobs in this account in the current region. | 
| Number of days that job records are retained | Each supported Region: 90 | No | The number of days that job records are retained. | 
| Number of days that job records are retained (Medical) | Each supported Region: 90 | No | The maximum number of days that job records are retained (Medical). | 
| Number of days that job records are retained for Call Analytics batch jobs | Each supported Region: 90 | No | The number of days job records are retained for Call Analytics batch jobs. | 
| Total language model limit | Each supported Region: 10 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-866105CB)  | The maximum total number of language models in this account in the current region. | 
| Total medical vocabulary limit | Each supported Region: 100 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-68305688)  | The maximum total number of medical vocabularies in this account in the current region. | 
| Total vocabulary limit | Each supported Region: 100 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-CB43679D)  | The maximum total number of vocabularies in this account in the current region. | 
| Transactions per second, CreateCallAnalyticsCategory | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-F1486348)  | The maximum number of CreateCallAnalyticsCategory requests that you can make per second from this account in the current region. | 
| Transactions per second, CreateLanguageModel | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-43B6F41B)  | The maximum number of CreateLanguageModel requests that you can make per second from this account in the current region. | 
| Transactions per second, CreateMedicalVocabulary | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-3AD094D8)  | The maximum number of CreateMedicalVocabulary requests that you can make per second from this account in the current region. | 
| Transactions per second, CreateVocabulary | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-0AC77AF0)  | The maximum number of CreateVocabulary requests that you can make per second from this account in the current region. | 
| Transactions per second, CreateVocabularyFilter | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-0781CA76)  | The maximum number of CreateVocabularyFilter requests that you can make per second from this account in the current region. | 
| Transactions per second, DeleteCallAnalyticsCategory | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-63677B99)  | The maximum number of DeleteCallAnalyticsCategory requests that you can make per second from this account in the current region. | 
| Transactions per second, DeleteCallAnalyticsJob | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-E1BA3DF5)  | The maximum number of DeleteCallAnalyticsJob requests that you can make per second from this account in the current region. | 
| Transactions per second, DeleteLanguageModel | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-C20EE45A)  | The maximum number of DeleteLanguageModel requests that you can make per second from this account in the current region. | 
| Transactions per second, DeleteMedicalScribeJob | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-3B3E6B1C)  | The maximum number of DeleteMedicalScribeJob requests that you can make per second from this account in the current region. | 
| Transactions per second, DeleteMedicalTranscriptionJob | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-2BEAA2BD)  | The maximum number of DeleteMedicalTranscriptionJob requests that you can make per second from this account in the current region. | 
| Transactions per second, DeleteMedicalVocabulary | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-32E8E80E)  | The maximum number of DeleteMedicalVocabulary requests that you can make per second from this account in the current region. | 
| Transactions per second, DeleteTranscriptionJob | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-46A3BCB8)  | The maximum number of DeleteTranscriptionJob requests that you can make per second from this account in the current region. | 
| Transactions per second, DeleteVocabulary | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-D8921821)  | The maximum number of DeleteVocabulary requests that you can make per second from this account in the current region. | 
| Transactions per second, DeleteVocabularyFilter | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-B778F7B9)  | The maximum number of DeleteVocabularyFilter requests that you can make per second from this account in the current region. | 
| Transactions per second, DescribeLanguageModel | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-2D3A6732)  | The maximum number of DescribeLanguageModel requests that you can make per second from this account in the current region. | 
| Transactions per second, GetCallAnalyticsCategory | Each supported Region: 20 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-8797DC7C)  | The maximum number of GetCallAnalyticsCategory requests that you can make per second from this account in the current region. | 
| Transactions per second, GetCallAnalyticsJob | Each supported Region: 20 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-D8B4403C)  | The maximum number of GetCallAnalyticsJob requests that you can make per second from this account in the current region. | 
| Transactions per second, GetMedicalScribeJob | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-0B1BA16E)  | The maximum number of GetMedicalScribeJob requests that you can make per second from this account in the current region. | 
| Transactions per second, GetMedicalScribeStream | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-C1AA6ACA)  | The maximum number of GetMedicalScribeStream requests that you can make per second from this account in the current region. | 
| Transactions per second, GetMedicalTranscriptionJob | Each supported Region: 30 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-85BCBEF8)  | The maximum number of GetMedicalTranscriptionJob requests that you can make per second from this account in the current region. | 
| Transactions per second, GetMedicalVocabulary | Each supported Region: 20 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-99087B15)  | The maximum number of GetMedicalVocabulary requests that you can make per second from this account in the current region. | 
| Transactions per second, GetTranscriptionJob | Each supported Region: 30 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-66FBE0A2)  | The maximum number of GetTranscriptionJob requests that you can make per second from this account in the current region. | 
| Transactions per second, GetVocabulary | Each supported Region: 20 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-70937EBD)  | The maximum number of GetVocabulary requests that you can make per second from this account in the current region. | 
| Transactions per second, GetVocabularyFilter | Each supported Region: 20 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-82ABD676)  | The maximum number of GetVocabularyFilter requests that you can make per second from this account in the current region. | 
| Transactions per second, ListCallAnalyticsCategories | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-1633BB4A)  | The maximum number of ListCallAnalyticsCategories requests that you can make per second from this account in the current region. | 
| Transactions per second, ListCallAnalyticsJobs | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-FAEFB7B8)  | The maximum number of ListCallAnalyticsJobs requests that you can make per second from this account in the current region. | 
| Transactions per second, ListLanguageModels | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-F8CF3791)  | The maximum number of ListLanguageModels requests that you can make per second from this account in the current region. | 
| Transactions per second, ListMedicalScribeJobs | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-D41CCA67)  | The maximum number of ListMedicalScribeJobs requests that you can make per second from this account in the current region. | 
| Transactions per second, ListMedicalTranscriptionJobs | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-15554767)  | The maximum number of ListMedicalTranscriptionJobs requests that you can make per second from this account in the current region. | 
| Transactions per second, ListMedicalVocabularies | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-DC7305D8)  | The maximum number of ListMedicalVocabularies requests that you can make per second from this account in the current region. | 
| Transactions per second, ListTagsForResource | Each supported Region: 50 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-1387188A)  | The maximum number of ListTagsForResource requests that you can make per second from this account in the current region. | 
| Transactions per second, ListTranscriptionJobs | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-14A2C961)  | The maximum number of ListTranscriptionJobs requests that you can make per second from this account in the current region. | 
| Transactions per second, ListVocabularies | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-B32D5B85)  | The maximum number of ListVocabularies requests that you can make per second from this account in the current region. | 
| Transactions per second, ListVocabularyFilters | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-072E1D50)  | The maximum number of ListVocabularyFilters requests that you can make per second from this account in the current region. | 
| Transactions per second, StartCallAnalyticsJob | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-50FAAE67)  | The maximum number of StartCallAnalyticsJob requests that you can make per second from this account in the current region. | 
| Transactions per second, StartCallAnalyticsStreamTranscription | Each supported Region: 25 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-F6E06B47)  | The maximum number of StartCallAnalyticsStreamTranscription requests that you can make per second from this account in the current region. | 
| Transactions per second, StartCallAnalyticsStreamTranscriptionWebsocket | Each supported Region: 25 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-49DA58C9)  | The maximum number of StartCallAnalyticsStreamTranscriptionWebsocket requests that you can make per second from this account in the current region. | 
| Transactions per second, StartMedicalScribeJob | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-DBAF8F96)  | The maximum number of StartMedicalScribeJob requests that you can make per second from this account in the current region. | 
| Transactions per second, StartMedicalScribeStream | Each supported Region: 2 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-70B0FC9B)  | The maximum number of StartMedicalScribeStream requests that you can make per second from this account in the current region. | 
| Transactions per second, StartMedicalStreamTranscription | Each supported Region: 25 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-A4098D0D)  | The maximum number of StartMedicalStreamTranscription requests that you can make per second from this account in the current region. | 
| Transactions per second, StartMedicalStreamTranscriptionWebsocket | Each supported Region: 25 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-B7245D62)  | The maximum number of StartMedicalStreamTranscriptionWebsocket requests that you can make per second from this account in the current region. | 
| Transactions per second, StartMedicalTranscriptionJob | Each supported Region: 25 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-C4B3DE72)  | The maximum number of StartMedicalTranscriptionJob requests that you can make per second from this account in the current region. | 
| Transactions per second, StartStreamTranscription | Each supported Region: 25 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-2B06FDCC)  | The maximum number of StartStreamTranscription requests that you can make per second from this account in the current region. | 
| Transactions per second, StartStreamTranscriptionWebSocket | Each supported Region: 25 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-00A7F8C0)  | The maximum number of StartStreamTranscriptionWebsocket requests that you can make per second from this account in the current region. | 
| Transactions per second, StartTranscriptionJob | Each supported Region: 25 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-1C614DC7)  | The maximum number of StartTranscriptionJob requests that you can make per second from this account in the current region. | 
| Transactions per second, TagResource | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-7D14E3E2)  | The maximum number of TagResource requests that you can make per second from this account in the current region. | 
| Transactions per second, UntagResource | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-84B1C0BA)  | The maximum number of UntagResource requests that you can make per second from this account in the current region. | 
| Transactions per second, UpdateCallAnalyticsCategory | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-4C7CC63C)  | The maximum number of UpdateCallAnalyticsCategory requests that you can make per second from this account in the current region. | 
| Transactions per second, UpdateLanguageModel | Each supported Region: 5 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-025543F3)  | The maximum number of UpdateLanguageModel requests that you can make per second from this account in the current region. | 
| Transactions per second, UpdateMedicalVocabulary | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-3A093139)  | The maximum number of UpdateMedicalVocabulary requests that you can make per second from this account in the current region. | 
| Transactions per second, UpdateVocabulary | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-50052249)  | The maximum number of UpdateVocabulary requests that you can make per second from this account in the current region. | 
| Transactions per second, UpdateVocabularyFilter | Each supported Region: 10 per second |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/transcribe/quotas/L-F49C59E1)  | The maximum number of UpdateVocabularyFilter requests that you can make per second from this account in the current region. | 

You can view your current quotas in the [AWS Management Console](https://console.aws.amazon.com/servicequotas/).