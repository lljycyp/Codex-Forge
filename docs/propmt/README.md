# 内置指令模板来源

## 当前导入快照

以下三份模板于 2026-11-12 从 [MDX-Tom/gpt-instruct](https://github.com/MDX-Tom/gpt-instruct) 的发布 ZIP 导入。

- 固定来源提交：[3ab84df64468bb74cc9eb4e5423660083953c44f](https://github.com/MDX-Tom/gpt-instruct/tree/3ab84df64468bb74cc9eb4e5423660083953c44f)。
- 本地模板名称和文件名只保留模型名，上游发布版本仅在本说明中记录。
- 模板正文按 ZIP 中的 Markdown 原始字节保存，仅调整本地文件名。
- 导入时分别核对 ZIP 和 Markdown 的 SHA-256；下表校验值对应仓库中的原始资源。

| 模板名称 | 本地文件 | 上游发布版本 | 上游状态 | ZIP 内原始文件名 |
| :--- | :--- | :--- | :--- | :--- |
| GPT-5.6 Sol | [gpt-5.6-sol.md](gpt-5.6-sol.md) | [gpt-5.6-sol-v45](https://github.com/MDX-Tom/gpt-instruct/blob/3ab84df64468bb74cc9eb4e5423660083953c44f/gpt-5.6-sol-v45.zip) | 稳定版 | `gpt-5.6-sol-unrestricted-v45.md` |
| GPT-6 Astra | [gpt-6-astra.md](gpt-6-astra.md) | [gpt-6-astra-v2-rc1](https://github.com/MDX-Tom/gpt-instruct/blob/3ab84df64468bb74cc9eb4e5423660083953c44f/gpt-6-astra-v2-rc1.zip) | 预发布版 | `gpt-6-astra-v2-rc1.md` |
| GPT-6.1 Sol | [gpt-6.1-sol.md](gpt-6.1-sol.md) | [gpt-6.1-sol-v1-rc2](https://github.com/MDX-Tom/gpt-instruct/blob/3ab84df64468bb74cc9eb4e5423660083953c44f/gpt-6.1-sol-v1-rc2.zip) | 预发布版 | `gpt-6.1-sol-v1-rc2.md` |

| 本地文件 | Markdown SHA-256 | 来源 ZIP SHA-256 |
| :--- | :--- | :--- |
| `gpt-5.6-sol.md` | `c71c50e2f7a303b5eebc2b24c0b1ca0d9c753e3240db05c3e472c679907898f7` | `c86c2c6d20a4d1155d87422f485eb37b77539132270918c002b5d8237a5adf54` |
| `gpt-6-astra.md` | `d6976b90b399b9e11df9430dd3663072288f1d858a4910b1e9d5109b3ae7e660` | `5c1d96f9aee25393af60245ac6c40b7850f641083a5162cad85762beedd6fc9d` |
| `gpt-6.1-sol.md` | `37382fb7082652e5b18c99fa5086fbc6d414993eaeae2ec7852ba372b031acac` | `007b8c5858110b809e5b90cd2c18bdc6965246aaee5af170b5487818b7055364` |

## 历史模板

以下两份原有资源继续保留，不属于上述导入快照：

- [gpt5.5-unrestricted.md](gpt5.5-unrestricted.md)
- [gpt-5.6-sol-unrestricted.md](gpt-5.6-sol-unrestricted.md)

启动时只补齐缺失的内置模板，不覆盖已有的同名文件，也不改变当前启用项。升级后可在指令模板页面手动选择新模板。

## 上游许可

本次导入的三份模板随附上游原始 [MIT License](LICENSE.gpt-instruct)，保留其中的版权声明和许可条款。打包时一并包含本目录中的模板、来源说明和许可文件。
