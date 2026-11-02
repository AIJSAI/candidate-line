Source: https://docs.aws.amazon.com/general/latest/gr/pol.md
Read (UTC): 2026-11-02T00:01:40Z
HTTP: 200



# Amazon Polly endpoints and quotas
<a name="pol"></a>

To connect programmatically to an AWS service, you use an endpoint. AWS services offer the following endpoint types in some or all of the AWS Regions that the service supports: IPv4 endpoints, dual-stack endpoints, and FIPS endpoints. Some services provide global endpoints. For more information, see [AWS service endpoints](rande.md).

Service quotas, also referred to as limits, are the maximum number of service resources or operations for your AWS account. For more information, see [AWS service quotas](aws_service_limits.md).

The following are the service endpoints and service quotas for this service.

## Service endpoints
<a name="pol_region"></a>


| Region Name | Region | Endpoint | Protocol | 
| --- | --- | --- | --- | 
| US East (Ohio) | us-east-2 |  polly.us-east-2.amazonaws.com <br /> polly-fips.us-east-2.api.aws <br /> polly-fips.us-east-2.amazonaws.com <br /> polly.us-east-2.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| US East (N. Virginia) | us-east-1 |  polly.us-east-1.amazonaws.com <br /> polly-fips.us-east-1.api.aws <br /> polly-fips.us-east-1.amazonaws.com <br /> polly.us-east-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| US West (N. California) | us-west-1 |  polly.us-west-1.amazonaws.com <br /> polly-fips.us-west-1.api.aws <br /> polly-fips.us-west-1.amazonaws.com <br /> polly.us-west-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| US West (Oregon) | us-west-2 |  polly.us-west-2.amazonaws.com <br /> polly-fips.us-west-2.api.aws <br /> polly-fips.us-west-2.amazonaws.com <br /> polly.us-west-2.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| Africa (Cape Town) | af-south-1 |  polly.af-south-1.amazonaws.com <br /> polly.af-south-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Hong Kong) | ap-east-1 |  polly.ap-east-1.amazonaws.com <br /> polly.ap-east-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Malaysia) | ap-southeast-5 |  polly.ap-southeast-5.amazonaws.com <br /> polly.ap-southeast-5.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Mumbai) | ap-south-1 |  polly.ap-south-1.amazonaws.com <br /> polly.ap-south-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Osaka) | ap-northeast-3 |  polly.ap-northeast-3.amazonaws.com <br /> polly.ap-northeast-3.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Seoul) | ap-northeast-2 |  polly.ap-northeast-2.amazonaws.com <br /> polly.ap-northeast-2.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Singapore) | ap-southeast-1 |  polly.ap-southeast-1.amazonaws.com <br /> polly.ap-southeast-1.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Sydney) | ap-southeast-2 |  polly.ap-southeast-2.amazonaws.com <br /> polly.ap-southeast-2.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Thailand) | ap-southeast-7 |  polly.ap-southeast-7.amazonaws.com <br /> polly.ap-southeast-7.api.aws  | HTTPS<br />HTTPS | 
| Asia Pacific (Tokyo) | ap-northeast-1 |  polly.ap-northeast-1.amazonaws.com <br /> polly.ap-northeast-1.api.aws  | HTTPS<br />HTTPS | 
| Canada (Central) | ca-central-1 |  polly.ca-central-1.amazonaws.com <br /> polly-fips.ca-central-1.api.aws <br /> polly-fips.ca-central-1.amazonaws.com <br /> polly.ca-central-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 
| Europe (Frankfurt) | eu-central-1 |  polly.eu-central-1.amazonaws.com <br /> polly.eu-central-1.api.aws  | HTTPS<br />HTTPS | 
| Europe (Ireland) | eu-west-1 |  polly.eu-west-1.amazonaws.com <br /> polly.eu-west-1.api.aws  | HTTPS<br />HTTPS | 
| Europe (London) | eu-west-2 |  polly.eu-west-2.amazonaws.com <br /> polly.eu-west-2.api.aws  | HTTPS<br />HTTPS | 
| Europe (Paris) | eu-west-3 |  polly.eu-west-3.amazonaws.com <br /> polly.eu-west-3.api.aws  | HTTPS<br />HTTPS | 
| Europe (Spain) | eu-south-2 |  polly.eu-south-2.amazonaws.com <br /> polly.eu-south-2.api.aws  | HTTPS<br />HTTPS | 
| Europe (Stockholm) | eu-north-1 |  polly.eu-north-1.amazonaws.com <br /> polly.eu-north-1.api.aws  | HTTPS<br />HTTPS | 
| Europe (Zurich) | eu-central-2 |  polly.eu-central-2.amazonaws.com <br /> polly.eu-central-2.api.aws  | HTTPS<br />HTTPS | 
| Middle East (Bahrain) | me-south-1 |  polly.me-south-1.amazonaws.com <br /> polly.me-south-1.api.aws  | HTTPS<br />HTTPS | 
| South America (São Paulo) | sa-east-1 |  polly.sa-east-1.amazonaws.com <br /> polly.sa-east-1.api.aws  | HTTPS<br />HTTPS | 
|  AWS GovCloud (US-West) | us-gov-west-1 |  polly.us-gov-west-1.amazonaws.com <br /> polly-fips.us-gov-west-1.api.aws <br /> polly-fips.us-gov-west-1.amazonaws.com <br /> polly.us-gov-west-1.api.aws  | HTTPS<br />HTTPS<br />HTTPS<br />HTTPS | 

## Service quotas
<a name="limits_polly"></a>


| Name | Default | Adjustable | Description | 
| --- | --- | --- | --- | 
| Lexicon count | Each supported Region: 100 | No | The maximum number of lexicons you can have in this account in the current region. | 
| Lexicon size | Each supported Region: 40,000 | No | The maximum size of a single lexicon in characters. | 
| Rate of GetSpeechSynthesisTask and ListSpeechSynthesisTasks requests | Each supported Region: 10 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-5C825113)  | The maximum number of GetSpeechSynthesisTask and ListSpeechSynthesisTasks requests per second that you can send in this account in the current region. | 
| Rate of StartSpeechSynthesisStream (generative) requests | Each supported Region: 8 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-B22AC499)  | The maximum number of StartSpeechSynthesisStream (generative engine) requests per second that you can send in this account in the current region. | 
| Rate of StartSpeechSynthesisTask (generative) requests | Each supported Region: 1 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-F041F337)  | The maximum number of StartSpeechSynthesisTask (generative engine) requests per second that you can send in this account in the current region. | 
| Rate of StartSpeechSynthesisTask (long-form) requests | Each supported Region: 1 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-E808FDFC)  | The maximum number of StartSpeechSynthesisTask (long-form engine) requests per second that you can send in this account in the current region. | 
| Rate of StartSpeechSynthesisTask (neural) requests | Each supported Region: 10 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-8C082E4C)  | The maximum number of StartSpeechSynthesisTask (neural engine) requests per second that you can send in this account in the current region. | 
| Rate of StartSpeechSynthesisTask (standard) requests | Each supported Region: 10 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-BE18DBC0)  | The maximum number of StartSpeechSynthesisTask (standard engine) requests per second that you can send in this account in the current region. | 
| Rate of SynthesizeSpeech (generative) requests | Each supported Region: 8 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-62670772)  | The maximum number of SynthesizeSpeech (generative engine) requests per second that you can send in this account in the current region. | 
| Rate of SynthesizeSpeech (long-form) requests | Each supported Region: 8 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-DA88EC07)  | The maximum number of SynthesizeSpeech (long-form engine) requests per second that you can send in this account in the current region. | 
| Rate of SynthesizeSpeech (neural) requests | Each supported Region: 8 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-0FE2012E)  | The maximum number of SynthesizeSpeech (neural engine) requests per second that you can send in this account in the current region. | 
| Rate of SynthesizeSpeech (standard) requests | Each supported Region: 80 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-9F5C26AE)  | The maximum number of SynthesizeSpeech (standard engine) requests per second that you can send in this account in the current region. This also includes DescribeVoices requests. | 
| Rate of lexicon management requests | Each supported Region: 5 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-F1BE3623)  | The maximum number of lexicon management requests per second that you can send in this account in the current region. This limit applies to following operations combined: ListLexicon, GetLexicon, PutLexicon, DeleteLexicon. | 
| Rate of tag management requests | Each supported Region: 5 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-ED1929D0)  | The maximum number of tag management requests per second that you can send in this account in the current region. This limit applies to following operations combined: TagResource, UntagResource, ListTagsForResource. | 
| StartSpeechSynthesisTask billed characters count | Each supported Region: 100,000 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-4F5CB3F8)  | Maximum size of the StartSpeechSynthesisTask input text in billed characters. SSML tags are not counted as billed characters. Applies to all engines. | 
| StartSpeechSynthesisTask lexicon count | Each supported Region: 5 | No | Maximum number of lexicons that can be used with StartSpeechSynthesisTask operation. Applies to all engines. | 
| StartSpeechSynthesisTask total characters limit | Each supported Region: 200,000 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-4BFD88C9)  | Maximum size of the StartSpeechSynthesisTask input text in characters, including SSML tags and whitespace. Applies to all engines. | 
| SynthesizeSpeech billed character count | Each supported Region: 3,000 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-E5FC9343)  | Maximum size of the SynthesizeSpeech input text in billed characters. SSML tags are not counted as billed characters. Applies to all engines. | 
| SynthesizeSpeech lexicon count | Each supported Region: 5 | No | Maximum number of lexicons that can be used with SynthesizeSpeech operation. Applies to all engines. | 
| SynthesizeSpeech total character count | Each supported Region: 6,000 |  [Yes](https://console.aws.amazon.com/servicequotas/home/services/polly/quotas/L-F8D2D09B)  | Maximum size of the SynthesizeSpeech input text in characters, including SSML tags and whitespace. Applies to all engines. | 

For more information, see [Quotas](https://docs.aws.amazon.com/polly/latest/dg/limits.html) in the *Amazon Polly Developer Guide*.