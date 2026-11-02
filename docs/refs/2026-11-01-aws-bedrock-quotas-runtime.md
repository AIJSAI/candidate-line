Source: https://docs.aws.amazon.com/bedrock/latest/userguide/quotas-runtime.md
Read (UTC): 2026-11-02T00:01:39Z
HTTP: 200



# Quotas for the bedrock-runtime endpoint
<a name="quotas-runtime"></a>

The `bedrock-runtime.{{region}}.amazonaws.com` endpoint is the primary inference endpoint for Amazon Bedrock. Inference traffic to this endpoint is governed by per-model token-based quotas. You can view these quotas in the [Service Quotas console](https://docs.aws.amazon.com/servicequotas/latest/userguide/gs-request-quota.html) by selecting **Amazon Bedrock** as the service, or in the [Amazon Bedrock service quotas](https://docs.aws.amazon.com/general/latest/gr/bedrock.html#limits_bedrock) table in the AWS General Reference.

**Note**  
A model's quotas on this endpoint are shared across every inference API you call it with, including [InvokeModel](inference-invoke.md), [Converse](conversation-inference.md), [Responses](inference-responses-api.md#bedrock-mantle-responses), and Chat Completions. Although the quota names refer to `InvokeModel`, they aren't per-API. Traffic to the `bedrock-mantle` endpoint is counted separately — see [Quotas for the bedrock-mantle endpoint](quotas-mantle.md).

## Quota types
<a name="quotas-runtime-types"></a>

Inference on the `bedrock-runtime` endpoint is governed by the following per-model quotas:


**bedrock-runtime per-model quotas**  

| Quota | Scope | Description | 
| --- | --- | --- | 
| Cross-Region InvokeModel tokens per minute for {{${model}}} | Per model, per Region | The maximum number of tokens per minute (input \+ output, combined) that your account can use for the model when invoked through a cross-Region inference profile. | 
| On-demand InvokeModel tokens per minute for {{${model}}} | Per model, per Region | The maximum number of tokens per minute (input \+ output, combined) that your account can use for the model when invoked on-demand in a single Region. | 
| Cross-Model Max Tokens Per Day | Per account, per Region | Maximum tokens per day across all supported Amazon Bedrock models for this account. Token count is estimated based on on-demand pricing; actual token consumption varies by model, input/output ratio, and cache usage. | 
| InvokeModel requests per minute for {{${model}}} | Per model, per Region | The maximum number of inference requests per minute that your account can submit for the model. RPM is enforced for some models on the bedrock-runtime endpoint and not others; see the Service Quotas console for the exact quotas that apply to your model. | 

The `bedrock-runtime` endpoint TPM quotas count input and output tokens together against a single per-model quota. The `bedrock-mantle` endpoint applies separate input-tokens-per-minute and output-tokens-per-minute quotas; for details, see [Quotas for the bedrock-mantle endpoint](quotas-mantle.md).

**Note**  
RPM quotas on the `bedrock-runtime` endpoint are model-specific. Some models – for example, Anthropic Claude Opus 4.7 and Claude Opus 4.8 – do not have an RPM quota and are governed solely by the token-based quotas described in this section. For models that do have an RPM quota, view the exact value in the [Service Quotas console](https://docs.aws.amazon.com/servicequotas/latest/userguide/gs-request-quota.html).

Output tokens are converted into quota usage through a model-specific burndown rate. For details on how token-based quotas are calculated and how the `max_tokens` request parameter affects deductions, see [How tokens are counted in Amazon Bedrock](quotas-token-burndown.md).

## Related runtime quotas
<a name="quotas-runtime-other"></a>

The following Amazon Bedrock capabilities are served through the `bedrock-runtime` endpoint and have their own separate quotas:
+ **Custom inference profiles** – Application-defined inference profiles that wrap an underlying model. See [Set up a model invocation resource using inference profiles](inference-profiles.md).
+ **Batch inference** – Asynchronous, large-volume inference jobs. See [Process multiple prompts with batch inference](batch-inference.md).
+ **Provisioned Throughput** – Reserved model-unit capacity. See [Increase model invocation capacity with Provisioned Throughput in Amazon Bedrock](prov-throughput.md).

These quotas apply only to the `bedrock-runtime` endpoint and are not exposed on the `bedrock-mantle` endpoint.

## Requesting a quota increase
<a name="quotas-runtime-increase"></a>

The steps for requesting a quota increase for your account depend on the value in the **Adjustable** column in the quotas table in [Amazon Bedrock service quotas](https://docs.aws.amazon.com/general/latest/gr/bedrock.html#limits_bedrock).

**Important**  
Before requesting a quota increase, verify that the model is not in a *Legacy* or *Deprecated* lifecycle status. Quota increases are not granted for models that are scheduled for retirement. Check the model's lifecycle status on the [Model lifecycle](model-lifecycle.md) page and consider migrating to the successor model instead.
+ If a quota is marked as **Yes**, you can adjust it by following the steps at [Requesting a Quota Increase](https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html) in the Service Quotas User Guide.
+ For any model, you can request an increase for the following quotas together:
  + Cross-Region InvokeModel tokens per minute for {{${model}}}
  + On-demand InvokeModel tokens per minute for {{${model}}}
  + Cross-Model Max Tokens Per Day

  To request an increase for any combination of these quotas, request an increase for the **Cross-Region InvokeModel tokens per minute for {{${model}}}** quota by following the steps at [Requesting a Quota Increase](https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html) in the Service Quotas User Guide. After you do so, the support team will reach out and offer you the option of also increasing the other two quotas.
**Note**  
Due to overwhelming demand, priority will be given to customers who generate traffic that consumes their existing quota allocation. Your request might be denied if you don't meet this condition.

For `bedrock-mantle` quota increases, see [Requesting a quota increase](quotas-mantle.md#quotas-mantle-increase).