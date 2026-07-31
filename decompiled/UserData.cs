using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

public class UserData
{
	[JsonInclude]
	[JsonPropertyName("PartyCharacters")]
	private List<Entity> _partyCharacters;

	[JsonInclude]
	[JsonPropertyName("LastRunCharacters")]
	private List<Entity> _lastRunCharacters;

	public Dictionary<string, int> LocalStats;

	public List<string> NewLoreStoreUnlocks;

	public string LastGameRunIdPlayed;

	public string LastPlayedVersionString;

	public eGameDifficulties LastUsedDifficulty;

	public bool ShouldAutoEndTurn;

	public bool OnlineMutliplayerEnabled;

	public bool FastForwardEnabled;

	public bool AutoFastForwardEnabled;

	public bool ChatFilterEnabled;

	public bool CrossplayEnabled;

	public bool CameraEdgeScrollingEnabled;

	public bool HoldToInspectEnabled;

	public bool ShowFooterControls;

	public bool CameraBobbingEnabled;

	public bool ArachnophobiaModeEnabled;

	public bool TutorialEnabled;

	public bool BlurEnabled;

	public bool ActionCameraEnabled;

	public int ActionCameraIntensity;

	public int CombatOverlayHUDSetting;

	public int ControllerNavigationSpeed;

	public bool ControllerVibrationEnabled;

	public bool AllowShareData;

	public float LastUserZoom;

	public Dictionary<string, float> VolumeOptions;

	public string Language;

	public List<string> SeenTutorialIds;

	public List<string> SeenGamePrompts;

	public string overrideBindingsJSON;

	public List<PlayerCharacterEncounterStoneHero> PlayerCharacterEncounterStoneHeroes;

	public List<PlayerCharacterEncounterDeadAdventurer> PlayerCharacterEncounterDeadAdventurers;

	public List<PlayerCharacterEncounterStoneHero> GlobalCharacterEncounterStoneHeroes;

	public List<PlayerCharacterEncounterDeadAdventurer> GlobalCharacterEncounterDeadAdventurers;

	[JsonIgnore]
	public List<Entity> PartyCharacters => _partyCharacters;

	[JsonIgnore]
	public List<Entity> LastRunCharacters => _lastRunCharacters;

	public void SetPartyCharacters(List<Entity> pEntities)
	{
		_partyCharacters = pEntities;
	}

	public void SetLastRunCharacters(List<Entity> pEntities)
	{
		_lastRunCharacters = pEntities;
	}

	public static UserData Create()
	{
		UserData userData = new UserData();
		userData.SetPartyCharacters(new List<Entity>());
		userData.SetLastRunCharacters(new List<Entity>());
		userData.OnlineMutliplayerEnabled = false;
		userData.ShouldAutoEndTurn = false;
		userData.FastForwardEnabled = true;
		userData.ChatFilterEnabled = true;
		userData.CrossplayEnabled = true;
		userData.ArachnophobiaModeEnabled = false;
		userData.TutorialEnabled = true;
		userData.BlurEnabled = true;
		userData.HoldToInspectEnabled = true;
		userData.ShowFooterControls = true;
		userData.CameraEdgeScrollingEnabled = true;
		userData.CameraBobbingEnabled = true;
		userData.ActionCameraEnabled = true;
		userData.AllowShareData = true;
		userData.ActionCameraIntensity = 1;
		userData.CombatOverlayHUDSetting = 4;
		userData.ControllerNavigationSpeed = 250;
		userData.ControllerVibrationEnabled = true;
		userData.LocalStats = new Dictionary<string, int>();
		userData.SeenTutorialIds = new List<string>();
		userData.SeenGamePrompts = new List<string>();
		userData.LastUserZoom = 0.55f;
		userData.VolumeOptions = new Dictionary<string, float>();
		userData.Language = "";
		userData.NewLoreStoreUnlocks = new List<string>();
		userData.LastUsedDifficulty = eGameDifficulties.APPRENTICE;
		UserData userData2 = userData;
		if (userData2.PlayerCharacterEncounterStoneHeroes == null)
		{
			userData2.PlayerCharacterEncounterStoneHeroes = new List<PlayerCharacterEncounterStoneHero>();
		}
		userData2 = userData;
		if (userData2.PlayerCharacterEncounterDeadAdventurers == null)
		{
			userData2.PlayerCharacterEncounterDeadAdventurers = new List<PlayerCharacterEncounterDeadAdventurer>();
		}
		userData2 = userData;
		if (userData2.GlobalCharacterEncounterStoneHeroes == null)
		{
			userData2.GlobalCharacterEncounterStoneHeroes = new List<PlayerCharacterEncounterStoneHero>();
		}
		userData2 = userData;
		if (userData2.GlobalCharacterEncounterDeadAdventurers == null)
		{
			userData2.GlobalCharacterEncounterDeadAdventurers = new List<PlayerCharacterEncounterDeadAdventurer>();
		}
		userData.VolumeOptions = new Dictionary<string, float>();
		userData.LastPlayedVersionString = VersionHelper.QueryVersion();
		return userData;
	}

	public static UserData Create(JsonElement pFromJSON)
	{
		JsonElement pJsonElement = pFromJSON;
		UserData userData = JsonHelper.Deserialize<UserData>(pJsonElement);
		if (!pJsonElement.TryGetProperty("CrossplayEnabled", out var value))
		{
			userData.CrossplayEnabled = true;
		}
		if (!pJsonElement.TryGetProperty("Language", out value))
		{
			userData.Language = "";
		}
		if (!pJsonElement.TryGetProperty("HoldToInspectEnabled", out value))
		{
			userData.HoldToInspectEnabled = true;
		}
		if (!pJsonElement.TryGetProperty("ShowFooterControls", out value))
		{
			userData.ShowFooterControls = true;
		}
		if (!pJsonElement.TryGetProperty("LastPlayedVersionString", out value) || SaveGameHelper.CompareVersion(userData.LastPlayedVersionString, "1.5.0") < 0)
		{
			userData.CombatOverlayHUDSetting = 4;
		}
		if (!pJsonElement.TryGetProperty("LastUsedDifficulty", out value))
		{
			userData.LastUsedDifficulty = eGameDifficulties.APPRENTICE;
		}
		_retrofitPlayerCharacterEncounterEquipment<PlayerCharacterEncounterStoneHero>(ref userData.GlobalCharacterEncounterStoneHeroes);
		_retrofitPlayerCharacterEncounterEquipment<PlayerCharacterEncounterStoneHero>(ref userData.PlayerCharacterEncounterStoneHeroes);
		_retrofitPlayerCharacterEncounterEquipment<PlayerCharacterEncounterDeadAdventurer>(ref userData.GlobalCharacterEncounterDeadAdventurers);
		_retrofitPlayerCharacterEncounterEquipment<PlayerCharacterEncounterDeadAdventurer>(ref userData.PlayerCharacterEncounterDeadAdventurers);
		userData.LastPlayedVersionString = VersionHelper.QueryVersion();
		if (userData._lastRunCharacters == null)
		{
			userData._lastRunCharacters = new List<Entity>();
		}
		if (userData._partyCharacters == null)
		{
			userData._partyCharacters = new List<Entity>();
		}
		UserData userData2 = userData;
		if (userData2.VolumeOptions == null)
		{
			userData2.VolumeOptions = new Dictionary<string, float>();
		}
		userData2 = userData;
		if (userData2.LocalStats == null)
		{
			userData2.LocalStats = new Dictionary<string, int>();
		}
		userData2 = userData;
		if (userData2.SeenTutorialIds == null)
		{
			userData2.SeenTutorialIds = new List<string>();
		}
		userData2 = userData;
		if (userData2.SeenGamePrompts == null)
		{
			userData2.SeenGamePrompts = new List<string>();
		}
		userData2 = userData;
		if (userData2.PlayerCharacterEncounterStoneHeroes == null)
		{
			userData2.PlayerCharacterEncounterStoneHeroes = new List<PlayerCharacterEncounterStoneHero>();
		}
		userData2 = userData;
		if (userData2.PlayerCharacterEncounterDeadAdventurers == null)
		{
			userData2.PlayerCharacterEncounterDeadAdventurers = new List<PlayerCharacterEncounterDeadAdventurer>();
		}
		userData2 = userData;
		if (userData2.GlobalCharacterEncounterStoneHeroes == null)
		{
			userData2.GlobalCharacterEncounterStoneHeroes = new List<PlayerCharacterEncounterStoneHero>();
		}
		userData2 = userData;
		if (userData2.GlobalCharacterEncounterDeadAdventurers == null)
		{
			userData2.GlobalCharacterEncounterDeadAdventurers = new List<PlayerCharacterEncounterDeadAdventurer>();
		}
		try
		{
			SaveGameHelper.MigrateUserStats(userData);
		}
		catch (Exception exception)
		{
			Debug.LogError("[UserData.Create] There was a fatal error when attempting to Migrate User stats:");
			Debug.LogException(exception);
		}
		return userData;
		static void _retrofitPlayerCharacterEncounterEquipment<T>(ref List<T> l) where T : PlayerCharacterEncounter
		{
			try
			{
				if (l == null)
				{
					return;
				}
				foreach (T item in l)
				{
					if (item.Equipment != null)
					{
						for (int i = 0; i < item.Equipment.Count; i++)
						{
							foreach (var wEAPON_CONFIG_NAME_CHANGE in SaveGameHelper.WEAPON_CONFIG_NAME_CHANGES)
							{
								if (item.Equipment[i] != null && item.Equipment[i].Equals(wEAPON_CONFIG_NAME_CHANGE.Item1))
								{
									item.Equipment[i] = wEAPON_CONFIG_NAME_CHANGE.Item2;
								}
							}
						}
					}
				}
			}
			catch (Exception arg)
			{
				Debug.LogError($"[UserData._retrofitPlayerCharacterEncounterEquipment] Exception: {arg}");
			}
		}
	}
}
