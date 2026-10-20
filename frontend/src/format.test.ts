import { describe, expect, it } from "vitest";
import { parseBRL, parseIntStrict, prettyName, validateNumber } from "./format";

describe("parseBRL", () => {
  it.each([
    ["1.234,56", 1234.56],
    ["1234,56", 1234.56],
    ["1234.56", 1234.56],
    ["1,234.56", 1234.56],
    ["R$ 1.234", 1234],
    ["R$ 1.234,50", 1234.5],
    ["-50", -50],
    ["−50", -50],
    ["-R$ 50,25", -50.25],
    ["(50)", -50],
    ["1.234", 1234],
    ["1.234.567", 1234567],
    ["1.234.567,89", 1234567.89],
    ["0,5", 0.5],
    ["0.5", 0.5],
    [",75", 0.75],
    ["12", 12],
    ["  10,00  ", 10],
    ["0", 0],
  ])("interpreta %j como %d", (input, expected) => {
    expect(parseBRL(input)).toBe(expected);
  });

  it.each(["", "   ", "abc", "12abc", "R$", "1,2,3", "1..2", "1.2.3", "--5", "1.234,5,6", "1234.567", "1,5.5", "0,123", "12,", "1.", "NaN"])(
    "rejeita %j", (input) => {
      expect(parseBRL(input)).toBeNull();
    });

  it("rejeita null, undefined e números não finitos", () => {
    expect(parseBRL(null)).toBeNull();
    expect(parseBRL(undefined)).toBeNull();
    expect(parseBRL(Infinity)).toBeNull();
  });

  it("não devolve -0", () => {
    expect(Object.is(parseBRL("-0"), 0)).toBe(true);
  });
});

describe("parseIntStrict", () => {
  it("aceita só inteiros sem sinal", () => {
    expect(parseIntStrict("100")).toBe(100);
    expect(parseIntStrict("1,5")).toBeNull();
    expect(parseIntStrict("-1")).toBeNull();
    expect(parseIntStrict("")).toBeNull();
  });
});

describe("validateNumber", () => {
  it("campo vazio é válido se opcional e erro se obrigatório", () => {
    expect(validateNumber("").error).toBeNull();
    expect(validateNumber("", { required: true }).error).toMatch(/Informe/);
  });
  it("bloqueia lixo, negativos e limites", () => {
    expect(validateNumber("abc").error).toMatch(/inválido/);
    expect(validateNumber("-5", { allowNegative: false }).error).toMatch(/negativo/);
    expect(validateNumber("150", { max: 100 }).error).toMatch(/máximo/);
    expect(validateNumber("1.234,56").value).toBe(1234.56);
  });
});

describe("prettyName", () => {
  it("converte caixa alta em título e preserva siglas", () => {
    expect(prettyName("IMOBILIARIA CENTRO LOCACOES")).toBe("Imobiliaria Centro Locacoes");
    expect(prettyName("ACME CONSULTORIA LTDA")).toBe("Acme Consultoria LTDA");
    expect(prettyName("COMPANHIA PAULISTA DE FORCA E LUZ")).toBe("Companhia Paulista de Forca e Luz");
  });
  it("remove prefixo de gateway e asteriscos", () => {
    expect(prettyName("Ifd*Restaurante Sabor")).toBe("Restaurante Sabor");
    expect(prettyName("Uber *Trip")).toBe("Uber Trip");
    expect(prettyName("PG *LOJA BOA")).toBe("Loja Boa");
  });
  it("mantém nomes com caixa mista e vazios", () => {
    expect(prettyName("Smart Fit")).toBe("Smart Fit");
    expect(prettyName(null)).toBe("");
  });
});
