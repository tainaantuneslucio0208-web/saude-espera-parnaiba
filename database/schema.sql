-- Banco criado pelo MYSQL_DATABASE do Docker; garantir charset
CREATE DATABASE IF NOT EXISTS saude_parnaiba CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE saude_parnaiba;

DROP TABLE IF EXISTS atendimentos;

CREATE TABLE atendimentos (
  id INT NOT NULL AUTO_INCREMENT,
  unidade VARCHAR(255) NOT NULL,
  especialidade VARCHAR(255) NOT NULL,
  data_atendimento DATE NOT NULL,
  hora_atendimento TIME NOT NULL,
  dia_semana VARCHAR(20) NOT NULL,
  tempo_espera_minutos DECIMAL(10,2) NOT NULL,
  classificacao_risco VARCHAR(50) NULL,
  PRIMARY KEY (id),
  KEY idx_unidade (unidade(80)),
  KEY idx_especialidade (especialidade(80)),
  KEY idx_dia_hora (dia_semana, data_atendimento),
  KEY idx_filtros_ranking (unidade(60), especialidade(60), dia_semana, tempo_espera_minutos),
  KEY idx_hora (hora_atendimento)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
